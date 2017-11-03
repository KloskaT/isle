
from insurancefirm import InsuranceFirm
from riskmodel import RiskModel
from reinsurancefirm import ReinsuranceFirm
import numpy as np
import scipy.stats
import math
import sys, pdb
import numba as nb
import isleconfig

if isleconfig.use_abce:
    import abce
    #print("abce imported")
#else:
#    print("abce not imported")



class InsuranceSimulation():
    def __init__(self, override_no_riskmodels, replic_ID, simulation_parameters):
        # override one-riskmodel case (this is to ensure all other parameters are truly identical for comparison runs)
        if override_no_riskmodels:
            simulation_parameters["no_riskmodels"] = override_no_riskmodels

        # save parameters
        if (replic_ID is None) or (isleconfig.force_foreground):
            self.background_run = False 
        else:
            self.background_run = True
        self.replic_ID = replic_ID
        self.simulation_parameters = simulation_parameters

        # unpack parameters, set up environment (distributions etc.)
        self.damage_distribution = scipy.stats.uniform(loc=0, scale=1)
        self.cat_separation_distribution = scipy.stats.expon(0, simulation_parameters["event_time_mean_separation"])
        self.risk_factor_lower_bound = simulation_parameters["risk_factor_lower_bound"]
        self.risk_factor_spread = simulation_parameters["risk_factor_upper_bound"] - simulation_parameters["risk_factor_lower_bound"]
        self.risk_factor_distribution = scipy.stats.uniform(loc=self.risk_factor_lower_bound, scale=self.risk_factor_spread)
        if not simulation_parameters["risk_factors_present"]:
            self.risk_factor_distribution = scipy.stats.uniform(loc=1.0, scale=0)
        #self.risk_value_distribution = scipy.stats.uniform(loc=100, scale=9900)
        self.risk_value_distribution = scipy.stats.uniform(loc=1000, scale=0)

        risk_factor_mean = self.risk_factor_distribution.mean()
        if np.isnan(risk_factor_mean):     # unfortunately scipy.stats.mean is not well-defined if scale = 0
            risk_factor_mean = self.risk_factor_distribution.rvs()

        # set initial market price (normalized, i.e. must be multiplied by value or excess-deductible)
        if self.simulation_parameters["expire_immediately"]:
            assert self.cat_separation_distribution.dist.name == "expon"
            expected_damage_frequency = 1 - scipy.stats.poisson(1 / self.simulation_parameters["event_time_mean_separation"] * \
                                                                self.simulation_parameters["mean_contract_runtime"]).pmf(0)
        else:
            expected_damage_frequency = self.simulation_parameters["mean_contract_runtime"] / \
                                                        self.cat_separation_distribution.mean()
        self.norm_premium = expected_damage_frequency * self.damage_distribution.mean() * \
                        risk_factor_mean * \
                        (1 + self.simulation_parameters["norm_profit_markup"])

        self.market_premium = self.norm_premium
        self.total_no_risks = simulation_parameters["no_risks"]

        # set up monetary system (should instead be with the customers, if customers are modeled explicitly)
        self.money_supply = self.simulation_parameters["money_supply"]
        self.obligations = []

        # set up risk categories
        self.riskcategories = list(range(self.simulation_parameters["no_categories"]))
        self.rc_event_schedule = []
        self.setup_risk_categories_caller()

        # set up risks
        risk_value_mean = self.risk_value_distribution.mean()
        if np.isnan(risk_value_mean):     # unfortunately scipy.stats.mean is not well-defined if scale = 0
            risk_value_mean = self.risk_value_distribution.rvs()
        rrisk_factors = self.risk_factor_distribution.rvs(size=self.simulation_parameters["no_risks"])
        rvalues = self.risk_value_distribution.rvs(size=self.simulation_parameters["no_risks"])
        rcategories = np.random.randint(0, self.simulation_parameters["no_categories"], size=self.simulation_parameters["no_risks"])
        self.risks = [{"risk_factor": rrisk_factors[i], "value": rvalues[i], "category": rcategories[i], "owner": self} for i in range(self.simulation_parameters["no_risks"])]

        # set up risk models
        inaccuracy = [[(0.5 if (i+j)%2==0 else 2.) for i in range(self.simulation_parameters["no_categories"])] for j in range(self.simulation_parameters["no_riskmodels"])]
        self.riskmodels = [RiskModel(self.damage_distribution, self.simulation_parameters["expire_immediately"], \
                    self.cat_separation_distribution, self.norm_premium, self.simulation_parameters["no_categories"], \
                    risk_value_mean, risk_factor_mean, \
                    self.simulation_parameters["norm_profit_markup"], inaccuracy[i]) \
                    for i in range(self.simulation_parameters["no_riskmodels"])]
        
        # prepare setting up agents (to be done from start.py)
        self.agent_parameters = {"insurancefirm": [], "reinsurance": []}    # TODO: rename reinsurance -> reinsurancefirm (also in start.py and below in method accept_agents

        # TODO: collapse the following two loops into one generic one?
        for i in range(simulation_parameters["no_insurancefirms"]):
            riskmodel = self.riskmodels[i % len(self.riskmodels)]
            self.agent_parameters["insurancefirm"].append({'id': i, 'initial_cash': simulation_parameters["initial_agent_cash"],
                                     'riskmodel': riskmodel, 'norm_premium': self.norm_premium,
                                     'profit_target': simulation_parameters["norm_profit_markup"],
                                     'initial_acceptance_threshold': simulation_parameters["initial_acceptance_threshold"],
                                     'acceptance_threshold_friction': simulation_parameters["acceptance_threshold_friction"],
                                     'reinsurance_limit': simulation_parameters["reinsurance_limit"],
                                     'interest_rate': simulation_parameters["interest_rate"]})
        for i in range(simulation_parameters["no_reinsurancefirms"]):
            riskmodel = self.riskmodels[i % len(self.riskmodels)]
            self.agent_parameters["reinsurance"].append({'id': i, 'initial_cash': simulation_parameters["initial_reinagent_cash"],
                                'riskmodel': riskmodel, 'norm_premium': self.norm_premium,
                                'profit_target': simulation_parameters["norm_profit_markup"],
                                'initial_acceptance_threshold': simulation_parameters["initial_acceptance_threshold"],
                                'acceptance_threshold_friction': simulation_parameters["acceptance_threshold_friction"],
                                'reinsurance_limit': simulation_parameters["reinsurance_limit"],
                                'interest_rate': simulation_parameters["interest_rate"]})
                                
        # set up remaining list variables
        
        # agent lists
        self.reinsurancefirms = []
        self.insurancefirms = []
        
        # lists of agent weights 
        self.insurancefirm_weights = []
        self.insurancefirm_new_weights = []
        self.reinsurancefirm_weights = []
        self.reinsurancefirm_new_weights = []

        # list of reinsurance risks offered for underwriting
        self.reinrisks = []
        
        # lists for logging history
        
        # sum insurance firms
        self.history_total_cash = []
        self.history_total_contracts = []
        self.history_total_operational = []
        # individual insurance firms
        self.history_individual_contracts = [[] for _ in range(simulation_parameters["no_insurancefirms"])]
        
        # sum reinsurance firms
        self.history_total_reincash = []
        self.history_total_reincontracts = []
        self.history_total_reinoperational = []
            
    
    def build_agents(self, agent_class, agent_class_string, parameters, agent_parameters):
        assert agent_parameters == self.agent_parameters[agent_class_string]
        agents = []
        for ap in agent_parameters:
            agents.append(agent_class(parameters, ap))
        return agents
        
    def accept_agents(self, agent_class_string, agents, agent_group):
        if agent_class_string == "insurancefirm":
            try:
                self.insurancefirms += agents
                self.insurancefirm_weights += [1 for i in agents]
                self.insurancefirm_new_weights += [agent.cash for agent in agents]
                self.insurancefirms_group = agent_group
            except:
                print(sys.exc_info())
                pdb.set_trace()
        elif agent_class_string == "reinsurance":
            try:
                self.reinsurancefirms += agents
                self.reinsurancefirm_weights += [1 for i in agents]
                self.reinsurancefirm_new_weights += [agent.cash for agent in agents]
                self.reinsurancefirms_group = agent_group
            except:
                print(sys.exc_info())
                pdb.set_trace()
        else:
            assert False, "Error: Unexpected agent class used"

    
    def iterate(self, t):
        print()
        print(t, ": ", len(self.risks))

        # adjust market premiums
        sum_capital = sum([agent.get_cash() for agent in self.insurancefirms])
        self.adjust_market_premium(capital=sum_capital)

        # pay obligations
        self.effect_payments(t)
        
        # identify perils and effect claims
        for categ_id in range(len(self.rc_event_schedule)):
            try:
                if len(self.rc_event_schedule[categ_id]) > 0:
                    assert self.rc_event_schedule[categ_id][0] >= t
            except:
                print("Something wrong; past events not deleted")
            if len(self.rc_event_schedule[categ_id]) > 0 and self.rc_event_schedule[categ_id][0] == t:
                self.rc_event_schedule[categ_id] = self.rc_event_schedule[categ_id][1:]
                
                self.inflict_peril(categ_id=categ_id, t=t)# TODO: consider splitting the following lines from this method and running it with nb.jit
            else:
                print("Next peril ", self.rc_event_schedule[categ_id])
        
        # shuffle risks (insurance and reinsurance risks)
        self.shuffle_risks()

        # reset reinweights
        self.reset_reinsurance_weights()
                    
        # iterate reinsurnace firm agents
        for reinagent in self.reinsurancefirms:
            reinagent.iterate(t)
        # TODO: is the following necessary for abce to work (log) properly?
        #if isleconfig.use_abce:
        #    self.reinsurancefirms_group.iterate(time=t)
        #else:
        #    for reinagent in self.reinsurancefirms:
        #        reinagent.iterate(t)
        
        # remove all non-accepted reinsurance risks
        self.reinrisks = []

        # reset weights
        self.reset_insurance_weights()
                    
        # iterate insurance firm agents
        for agent in self.insurancefirms:
            agent.iterate(t)
        # TODO: is the following necessary for abce to work (log) properly?
        #if isleconfig.use_abce:
        #    self.insurancefirms_group.iterate(time=t)
        #else:
        #    for agent in self.insurancefirms:
        #        agent.iterate(t)
        
    def save_data(self):
        # collect data
        total_cash_no = sum([insurancefirm.cash for insurancefirm in self.insurancefirms])
        total_contracts_no = sum([len(insurancefirm.underwritten_contracts) for insurancefirm in self.insurancefirms])
        total_reincash_no = sum([reinsurancefirm.cash for reinsurancefirm in self.reinsurancefirms])
        total_reincontracts_no = sum([len(reinsurancefirm.underwritten_contracts) for reinsurancefirm in self.reinsurancefirms])
        operational_no = sum([insurancefirm.operational for insurancefirm in self.insurancefirms])
        reinoperational_no = sum([reinsurancefirm.operational for reinsurancefirm in self.reinsurancefirms])
        self.history_total_cash.append(total_cash_no)
        self.history_total_contracts.append(total_contracts_no)
        self.history_total_operational.append(operational_no)
        self.history_total_reincash.append(total_reincash_no)
        self.history_total_reincontracts.append(total_reincontracts_no)
        self.history_total_reinoperational.append(reinoperational_no)
        
        individual_contracts_no = [len(insurancefirm.underwritten_contracts) for insurancefirm in self.insurancefirms]
        for i in range(len(individual_contracts_no)):
            self.history_individual_contracts[i].append(individual_contracts_no[i])
    
    def advance_round(self, *args):
        pass
    
    def finalize(self, *args):
        self.log()
        pass

    def inflict_peril(self, categ_id, t):
        affected_contracts = [contract for insurer in self.insurancefirms for contract in insurer.underwritten_contracts if contract.category == categ_id]
        no_affected = len(affected_contracts)
        damage = self.damage_distribution.rvs()
        print("**** PERIL ", damage)
        damagevalues = np.random.beta(1, 1./damage -1, size=no_affected)
        uniformvalues = np.random.uniform(0, 1, size=no_affected)
        [contract.explode(self.simulation_parameters["expire_immediately"], t, uniformvalues[i], damagevalues[i]) for i, contract in enumerate(affected_contracts)]
    
    def receive_obligation(self, amount, recipient, due_time):
        obligation = {"amount": amount, "recipient": recipient, "due_time": due_time}
        self.obligations.append(obligation)

    def effect_payments(self, time):
        due = [item for item in self.obligations if item["due_time"]<=time]
        #print("SIMULATION obligations: ", len(self.obligations), " of which are due: ", len(due))
        self.obligations = [item for item in self.obligations if item["due_time"]>time]
        sum_due = sum([item["amount"] for item in due])
        for obligation in due:
            self.pay(obligation["amount"], obligation["recipient"])

    def pay(self, amount, recipient):
        #print("SIMULATION paying ", amount)
        try:
            assert self.money_supply > amount
        except:
            print("Something wrong: economy out of money")
        self.money_supply -= amount
        recipient.receive(amount)

    def receive(self, amount):
        ## Not necessary in ABCE style
        #pass
        # Non-ABCE style
        """Method to accept cash payments."""
        self.money_supply += amount

    @nb.jit
    def reset_reinsurance_weights(self):
        self.reinsurancefirm_weights = np.asarray(self.reinsurancefirm_new_weights) / \
                                    sum(self.reinsurancefirm_new_weights) * len(self.reinrisks)
        self.reinsurancefirm_weights = np.int64(np.floor(self.reinsurancefirm_weights))
        #self.reinsurancefirm_new_weights = [0 for i in self.reinsurancefirms]
        #reinsurancefirm_new_weights2 = [0 for i in self.reinsurancefirms]
        self.reinsurancefirm_new_weights = list(np.zeros(len(self.reinsurancefirms)))
        #assert self.reinsurancefirm_new_weights == reinsurancefirm_new_weights2
        
        #self.reinsurancefirm_new_weights = self.reinsurancefirms.zeros()
        
    @nb.jit
    def reset_insurance_weights(self):
        self.insurancefirm_weights = np.asarray(self.insurancefirm_new_weights) / \
                                   sum(self.insurancefirm_new_weights) * len(self.risks)
        self.insurancefirm_weights = np.int64(np.floor(self.insurancefirm_weights))
        #self.insurancefirm_new_weights = [0 for i in self.insurancefirms]
        self.insurancefirm_new_weights = list(np.zeros(len(self.insurancefirms)))
        print('@', self.insurancefirm_weights)

    @nb.jit
    def shuffle_risks(self):
        np.random.shuffle(self.reinrisks)
        np.random.shuffle(self.risks)

    def adjust_market_premium(self, capital):
        self.market_premium = self.norm_premium * (self.simulation_parameters["upper_price_limit"] - capital / (self.norm_premium * self.simulation_parameters["no_risks"]))
        if self.market_premium < self.norm_premium * self.simulation_parameters["lower_price_limit"]:
            self.market_premium = self.norm_premium * self.simulation_parameters["lower_price_limit"]

    def get_market_premium(self):
        return self.market_premium

    def append_reinrisks(self, item):
        if(len(item) > 0):
            self.reinrisks.append(item)

    def remove_reinrisks(self,risko):
        if(risko != None):
            self.reinrisks.remove(risko)

    def get_reinrisks(self):
        np.random.shuffle(self.reinrisks)
        return self.reinrisks

    def solicit_insurance_requests(self, id, cash):
        self.insurancefirm_new_weights[id] = cash
        risks_to_be_sent = self.risks[:int(self.insurancefirm_weights[id])]
        self.risks = self.risks[int(self.insurancefirm_weights[id]):]
        print("Number of risks", len(risks_to_be_sent))
        return risks_to_be_sent

    def solicit_reinsurance_requests(self, id, cash):
        self.reinsurancefirm_new_weights[id] = cash
        reinrisks_to_be_sent = self.reinrisks[:self.reinsurancefirm_weights[id]]
        self.reinrisks = self.reinrisks[self.reinsurancefirm_weights[id]:]
        print("Number of risks",len(reinrisks_to_be_sent))
        return reinrisks_to_be_sent

    def return_risks(self, not_accepted_risks):
        self.risks += not_accepted_risks

    def return_reinrisks(self, not_accepted_risks):
        self.reinrisks += not_accepted_risks

    def setup_risk_categories(self):
        for i in self.riskcategories:
            event_schedule = []
            total = 0
            while (total < self.simulation_parameters["max_time"]):
                separation_time = self.cat_separation_distribution.rvs()
                total += int(math.ceil(separation_time))
                if total < self.simulation_parameters["max_time"]:
                    event_schedule.append(total)
            self.rc_event_schedule.append(event_schedule)

    def setup_risk_categories_caller(self):
        #if self.background_run:
        if self.replic_ID is not None:
            if isleconfig.replicating:
                self.restore_state_and_risk_categories()
            else:
                self.setup_risk_categories()
                self.save_state_and_risk_categories()
        else:
            self.setup_risk_categories()

    def save_state_and_risk_categories(self):
        # save numpy Mersenne Twister state
        mersennetwoster_randomseed = str(np.random.get_state())
        mersennetwoster_randomseed = mersennetwoster_randomseed.replace("\n","").replace("array", "np.array").replace("uint32", "np.uint32")
        wfile = open("data/replication_randomseed.dat","a")
        wfile.write(mersennetwoster_randomseed+"\n")
        wfile.close()
        # save event schedule
        wfile = open("data/replication_rc_event_schedule.dat","a")
        wfile.write(str(self.rc_event_schedule)+"\n")
        wfile.close()
        
    def restore_state_and_risk_categories(self):
        rfile = open("data/replication_rc_event_schedule.dat","r")
        found = False
        for i, line in enumerate(rfile):
            #print(i, self.replic_ID)
            if i == self.replic_ID:
                self.rc_event_schedule = eval(line)
                found = True
        rfile.close()
        assert found, "rc event schedule for current replication ID number {0:d} not found in data file. Exiting.".format(self.replic_ID)
        rfile = open("data/replication_randomseed.dat","r")
        found = False
        for i, line in enumerate(rfile):
            #print(i, self.replic_ID)
            if i == self.replic_ID:
                mersennetwister_randomseed = eval(line)
                found = True
        rfile.close()
        np.random.set_state(mersennetwister_randomseed)
        assert found, "mersennetwister randomseed for current replication ID number {0:d} not found in data file. Exiting.".format(self.replic_ID)

    def log(self):
        if self.background_run:
            if isleconfig.oneriskmodel:
                to_log = self.replication_log_prepare_oneriskmodel()
            else:
                to_log = self.replication_log_prepare()
        else:
            to_log = self.single_log_prepare()
        
        for filename, data, operation_character in to_log:
            wfile = open(filename, operation_character)
            wfile.write(str(data) + "\n")
            wfile.close()
    
    def replication_log_prepare(self):
        to_log = []
        to_log.append(("data/two_operational.dat", self.history_total_operational, "a"))
        to_log.append(("data/two_contracts.dat", self.history_total_contracts, "a"))
        to_log.append(("data/two_cash.dat", self.history_total_cash, "a"))
        to_log.append(("data/two_reinoperational.dat", self.history_total_reinoperational, "a"))
        to_log.append(("data/two_reincontracts.dat", self.history_total_reincontracts, "a"))
        to_log.append(("data/two_reincash.dat", self.history_total_reincash, "a"))
        return to_log

    def replication_log_prepare_oneriskmodel(self):
        to_log = []
        to_log.append(("data/one_operational.dat", self.history_total_operational, "a"))
        to_log.append(("data/one_contracts.dat", self.history_total_contracts, "a"))
        to_log.append(("data/one_cash.dat", self.history_total_cash, "a"))
        to_log.append(("data/one_reinoperational.dat", self.history_total_reinoperational, "a"))
        to_log.append(("data/one_reincontracts.dat", self.history_total_reincontracts, "a"))
        to_log.append(("data/one_reincash.dat", self.history_total_reincash, "a"))
        return to_log

    def single_log_prepare(self):
        to_log = []
        to_log.append(("data/operational.dat", self.history_total_operational, "w"))
        to_log.append(("data/contracts.dat", self.history_total_contracts, "w"))
        to_log.append(("data/cash.dat", self.history_total_cash, "w"))
        to_log.append(("data/reinoperational.dat", self.history_total_reinoperational, "w"))
        to_log.append(("data/reincontracts.dat", self.history_total_reincontracts, "w"))
        to_log.append(("data/reincash.dat", self.history_total_reincash, "w"))
        return to_log

#if __name__ == "__main__":
#    arg = None
#    if len(sys.argv) > 1:
#        arg = int(sys.argv[1])
#    S = InsuranceSimulation(replic_ID = arg)
#    S.run()