# import common packages

import argparse
import hashlib
import numpy as np
import os
import pickle
import random
from typing import MutableMapping, MutableSequence

import calibrationscore
import insurancesimulation

# import config file and apply configuration
import isleconfig
import logger

simulation_parameters = isleconfig.simulation_parameters
filepath = None
overwrite = False
override_no_riskmodels = False

"""Creates data file for logs if does not exist"""
if not os.path.isdir("data"):
    if os.path.exists("data"):
        raise FileExistsError("./data exists as regular file. This filename is required for the logging directory")
    os.makedirs("data")


# main function
def main(sim_params: MutableMapping, rc_event_schedule: MutableSequence[MutableSequence[int]],
         rc_event_damage: MutableSequence[MutableSequence[float]], np_seed: int, random_seed: int, save_iteration: int,
         replic_id: int, requested_logs: MutableSequence = None,resume: bool = False) -> MutableSequence:
    if not resume:
        np.random.seed(np_seed)
        random.seed(random_seed)

        sim_params["simulation"] = simulation = insurancesimulation.InsuranceSimulation(override_no_riskmodels, replic_id,
                                                sim_params, rc_event_schedule, rc_event_damage)
        time = 0
    else:
        d = load_simulation()
        np.random.set_state(d["np_seed"])
        random.setstate(d["random_seed"])
        time = d["time"]
        simulation = d["simulation"]
        sim_params = d["simulation_parameters"]
        for key in d["isleconfig"]:
            isleconfig.__dict__[key] = d["isleconfig"][key]
        isleconfig.simulation_parameters = sim_params
    for t in range(time, sim_params["max_time"]):
        # Main time iteration loop
        simulation.iterate(t)

        # log data
        simulation.save_data()

        # Don't save at t=0 or if the simulation has just finished
        if t % save_iteration == 0 and 0 < t < sim_params["max_time"]:
            # Need to use t+1 as resume will start at time saved
            save_simulation(t + 1, simulation, sim_params, exit_now=False)

    # It is required to return this list to download all the data generated by a single run of the model from the cloud.
    return simulation.obtain_log(requested_logs)


def save_simulation(t: int, sim: insurancesimulation.InsuranceSimulation, sim_param: MutableMapping, exit_now: bool = False,) -> None:
    d = {"np_seed": np.random.get_state(), "random_seed": random.getstate(), "time": t, "simulation": sim,
         "simulation_parameters": sim_param, "isleconfig": {}}
    for key in isleconfig.__dict__:
        if not key.startswith("__"):
            d["isleconfig"][key] = isleconfig.__dict__[key]

    with open("data/simulation_save.pkl", "bw") as wfile:
        pickle.dump(d, wfile, protocol=pickle.HIGHEST_PROTOCOL)
    with open("data/simulation_save.pkl", "br") as rfile:
        file_contents = rfile.read()
    print("\nSaved simulation with hash:",hashlib.sha512(str(file_contents).encode()).hexdigest())

    if exit_now:
        exit(0)


def load_simulation() -> dict:
    # TODO: Fix! This doesn't work, the retrieved file is different to the saved one.
    with open("data/simulation_save.pkl", "br") as rfile:
        print("\nLoading simulation with hash:", hashlib.sha512(str(rfile.read()).encode()).hexdigest())
        rfile.seek(0)
        file_contents = pickle.load(rfile)
    return file_contents


# main entry point
if __name__ == "__main__":

    """ use argparse to handle command line arguments"""
    parser = argparse.ArgumentParser(description="Model the Insurance sector")
    parser.add_argument("-f", "--file", action="store",
                        help="the file to store the initial randomness in. Will be stored in ./data and appended with "
                             ".islestore (if it is not already). The default filepath is "
                             "./data/risk_event_schedules.islestore, which will be overwritten event if --overwrite is "
                             "not passed!")
    parser.add_argument("-r", "--replicating", action="store_true", help="if this is a simulation run designed to replicate another, override the config file parameter. "
        "You probably want to specify the --file to read from.",)
    parser.add_argument("-o", "--overwrite", action="store_true", help="allows overwriting of the file specified by -f")
    parser.add_argument("-p", "--showprogress", action="store_true", help="show timesteps")
    parser.add_argument("-v", "--verbose", action="store_true", help="more detailed output")
    parser.add_argument("--resume", action="store_true", help="Resume the simulation from a previous save in "
                        "./data/simulation_save.pkl. All other arguments will be ignored",)
    parser.add_argument("--oneriskmodel", action="store_true", help="allow overriding the number of riskmodels from the "
                                                                    "standard config (with 1)",)
    parser.add_argument("--riskmodels", type=int, choices=[1, 2, 3, 4], help="allow overriding the number of riskmodels "
                        "from standard config (with 1 or other numbers). Overrides --oneriskmodel",)
    parser.add_argument("--randomseed", type=float, help="allow setting of numpy random seed")
    parser.add_argument("--foreground", action="store_true",
                        help="force foreground runs even if replication ID is given, which defaults to background runs")
    parser.add_argument("--shownetwork", action="store_true", help="show reinsurance relations as network")
    parser.add_argument("--save_iterations", type=int, help="number of iterations to iterate before saving world state")
    args = parser.parse_args()

    if args.oneriskmodel:
        isleconfig.oneriskmodel = True
        override_no_riskmodels = 1
    if args.riskmodels:
        override_no_riskmodels = args.riskmodels
    if args.file:
        filepath = args.file
    if args.overwrite:
        overwrite = True
    if args.replicating:
        isleconfig.replicating = True
    if args.randomseed:
        randomseed = args.randomseed
        seed = int(randomseed)
    else:
        np.random.seed()
        seed = np.random.randint(0, 2 ** 31 - 1)
    if args.foreground:
        isleconfig.force_foreground = True
    if args.shownetwork:
        isleconfig.show_network = True
    if args.showprogress:
        isleconfig.showprogress = True
    if args.verbose:
        isleconfig.verbose = True
    if args.save_iterations:
        save_iter = args.save_iterations
    else:
        # Disable saving unless save_iter is given. It doesn't work anyway # TODO
        save_iter = isleconfig.simulation_parameters["max_time"] + 2

    if not args.resume:
        from setup_simulation import SetupSim

        setup = SetupSim()  # Here the setup for the simulation is done.

        # Only one ensemble. This part will only be run locally (laptop).
        [general_rc_event_schedule, general_rc_event_damage, np_seeds, random_seeds] = \
            setup.obtain_ensemble(1, filepath, overwrite)
    else:
        # We are resuming, so all of the necessary setup will be loaded from a file
        general_rc_event_schedule = (general_rc_event_damage) = np_seeds = random_seeds = [None]

    # Run the main program
    # Note that we pass the filepath as the replic_ID
    log = main(simulation_parameters, general_rc_event_schedule[0], general_rc_event_damage[0], np_seeds[0],
               random_seeds[0], save_iter, replic_id=1, resume=args.resume)

    replic_ID = 1
    """ Restore the log at the end of the single simulation run for saving and for potential further study """
    is_background = (not isleconfig.force_foreground) and (isleconfig.replicating or (replic_ID in locals()))
    L = logger.Logger()
    L.restore_logger_object(list(log))
    L.save_log(is_background)
    if isleconfig.save_network:
        L.save_network_data(ensemble=False)
    
    """ Obtain calibration score """
    CS = calibrationscore.CalibrationScore(L)
    score = CS.test_all()
