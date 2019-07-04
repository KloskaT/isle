# import common packages
import numpy as np
import scipy.stats
import math
import sys, pdb
import argparse
import os
import pickle
import hashlib
import random

# import config file and apply configuration
import isleconfig

import insurancesimulation
import insurancefirm
import reinsurancefirm
import logger
import calibrationscore

simulation_parameters = isleconfig.simulation_parameters
replic_ID = None
override_no_riskmodels = False

# ensure that logging directory exists
if not os.path.isdir("data"):
    if os.path.exists("data"):
        raise FileExistsError(
            "./data exists as regular file. This filename is required for the logging directory"
        )
    os.makedirs("data")


# main function
def main(
    simulation_parameters,
    rc_event_schedule,
    rc_event_damage,
    np_seed,
    random_seed,
    save_iter,
    requested_logs=None,
):
    np.random.seed(np_seed)
    random.seed(random_seed)

    simulation_parameters[
        "simulation"
    ] = simulation = insurancesimulation.InsuranceSimulation(
        override_no_riskmodels,
        replic_ID,
        simulation_parameters,
        rc_event_schedule,
        rc_event_damage,
    )

    # create agents: insurance firms
    insurancefirms_group = simulation.build_agents(
        insurancefirm.InsuranceFirm,
        "insurancefirm",
        parameters=simulation_parameters,
        agent_parameters=simulation.agent_parameters["insurancefirm"],
    )

    simulation.accept_agents("insurancefirm", insurancefirms_group)

    # create agents: reinsurance firms
    reinsurancefirms_group = simulation.build_agents(
        reinsurancefirm.ReinsuranceFirm,
        "reinsurancefirm",
        parameters=simulation_parameters,
        agent_parameters=simulation.agent_parameters["reinsurancefirm"],
    )
    simulation.accept_agents("reinsurancefirm", reinsurancefirms_group)

    # time iteration
    for t in range(simulation_parameters["max_time"]):
        # create new agents        # TODO: write method for this; this code block is executed almost identically 4 times
        # In fact this should probably all go in insurancesimulation.py, as part of simulation.iterate(t)
        if simulation.insurance_firm_enters_market(agent_type="InsuranceFirm"):
            parameters = [
                np.random.choice(simulation.agent_parameters["insurancefirm"])
            ]  # Which of these should be used?
            parameters = [
                simulation.agent_parameters["insurancefirm"][
                    simulation.insurance_entry_index()
                ]
            ]
            # As far as I can tell, there are only {no_riskmodels} distinct values for parameters, why does
            # simulation.agent_parameters["insurancefirm"] need to have length {no_insurancefirms}?
            # Also why do the new insurers always use the least popular risk model?
            parameters[0]["id"] = simulation.get_unique_insurer_id()
            new_insurance_firm = simulation.build_agents(
                insurancefirm.InsuranceFirm,
                "insurancefirm",
                parameters=simulation_parameters,
                agent_parameters=parameters,
            )
            insurancefirms_group += new_insurance_firm
            simulation.accept_agents("insurancefirm", new_insurance_firm, time=t)

        if simulation.insurance_firm_enters_market(agent_type="ReinsuranceFirm"):
            parameters = [
                np.random.choice(simulation.agent_parameters["reinsurancefirm"])
            ]
            # The reinsurance firms do just pick a random riskmodel when they are created. It is weighted by the initial
            # distribution, I think # TODO: is this right?
            parameters[0]["initial_cash"] = simulation.reinsurance_capital_entry()
            # Since the value of the reinrisks varies overtime it makes sense that the market entry of reinsures
            # depends on those values. The method world.reinsurance_capital_entry() determines the capital
            # market entry of reinsurers.
            parameters = [
                simulation.agent_parameters["reinsurancefirm"][
                    simulation.reinsurance_entry_index()
                ]
            ]
            parameters[0]["id"] = simulation.get_unique_reinsurer_id()
            new_reinsurance_firm = simulation.build_agents(
                reinsurancefirm.ReinsuranceFirm,
                "reinsurancefirm",
                parameters=simulation_parameters,
                agent_parameters=parameters,
            )
            reinsurancefirms_group += new_reinsurance_firm
            simulation.accept_agents("reinsurancefirm", new_reinsurance_firm, time=t)

        # iterate simulation
        simulation.iterate(t)

        # log data
        simulation.save_data()

        if t % 50 == save_iter:
            save_simulation(t, simulation, simulation_parameters, exit_now=False)

    # finish simulation, write logs
    simulation.finalize()

    return simulation.obtain_log(
        requested_logs
    )  # It is required to return this list to download all the data generated by a single run of the model from the cloud.


# save function
def save_simulation(t, sim, sim_param, exit_now=False):
    d = {
        "np_seed": np.random.get_state(),
        "random_seed": random.getstate(),
        "time": t,
        "simulation": sim,
        "simulation_parameters": sim_param,
    }
    with open("data/simulation_save.pkl", "bw") as wfile:
        pickle.dump(d, wfile, protocol=pickle.HIGHEST_PROTOCOL)
    with open("data/simulation_save.pkl", "br") as rfile:
        file_contents = rfile.read()
    # print("\nSimulation hashes: ", hashlib.sha512(str(d).encode()).hexdigest(), "; ",  hashlib.sha512(str(file_contents).encode()).hexdigest())
    # note that the hash over the dict is for some reason not identical between runs. The hash over the state saved to the file is.
    print(
        "\nSimulation hash: ", hashlib.sha512(str(file_contents).encode()).hexdigest()
    )
    if exit_now:
        exit(0)


# main entry point
if __name__ == "__main__":

    """ use argparse to handle command line arguments"""
    parser = argparse.ArgumentParser(description="Model the Insurance sector")
    parser.add_argument("--abce", action="store_true", help="[REMOVED] use abce")
    parser.add_argument(
        "--oneriskmodel",
        action="store_true",
        help="allow overriding the number of riskmodels from the standard config (with 1)",
    )
    parser.add_argument(
        "--riskmodels",
        type=int,
        choices=[1, 2, 3, 4],
        help="allow overriding the number of riskmodels from standard config (with 1 or other numbers)",
    )
    parser.add_argument(
        "--replicid",
        type=int,
        help="if replication ID is given, pass this to the simulation so that the risk profile can be restored",
    )
    parser.add_argument(
        "--replicating",
        action="store_true",
        help="if this is a simulation run designed to replicate another, override the config file parameter",
    )
    parser.add_argument(
        "--randomseed", type=float, help="allow setting of numpy random seed"
    )
    parser.add_argument(
        "--foreground",
        action="store_true",
        help="force foreground runs even if replication ID is given (which defaults to background runs)",
    )
    parser.add_argument(
        "--shownetwork",
        action="store_true",
        help="show reinsurance relations as network",
    )
    parser.add_argument(
        "-p", "--showprogress", action="store_true", help="show timesteps"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="more detailed output"
    )
    parser.add_argument(
        "--save_iterations",
        type=int,
        help="number of iterations to iterate before saving world state",
    )
    args = parser.parse_args()

    if args.abce:
        raise Exception("ABCE is not and will not be supported")
    if args.oneriskmodel:
        isleconfig.oneriskmodel = True
        override_no_riskmodels = 1
    if args.riskmodels:
        override_no_riskmodels = args.riskmodels
    if args.replicid is not None:  # TODO: this is broken, must be fixed or removed
        replic_ID = args.replicid
    if args.replicating:
        isleconfig.replicating = True
        assert (
            replic_ID is not None
        ), "Error: Replication requires a replication ID to identify run to be replicated"
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
        save_iter = 200

    from setup import SetupSim

    setup = SetupSim()  # Here the setup for the simulation is done.
    [
        general_rc_event_schedule,
        general_rc_event_damage,
        np_seeds,
        random_seeds,
    ] = setup.obtain_ensemble(
        1
    )  # Only one ensemble. This part will only be run locally (laptop).

    # Run the main program
    log = main(
        simulation_parameters,
        general_rc_event_schedule[0],
        general_rc_event_damage[0],
        np_seeds[0],
        random_seeds[0],
        save_iter,
    )

    """ Restore the log at the end of the single simulation run for saving and for potential further study """
    is_background = (not isleconfig.force_foreground) and (
        isleconfig.replicating or (replic_ID in locals())
    )
    L = logger.Logger()
    L.restore_logger_object(list(log))
    L.save_log(is_background)

    """ Obtain calibration score """
    CS = calibrationscore.CalibrationScore(L)
    score = CS.test_all()
