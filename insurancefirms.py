from __future__ import annotations
from typing import Optional, Tuple, MutableSequence, Mapping

import numpy as np

from metainsuranceorg import MetaInsuranceOrg
import catbond
from reinsurancecontract import ReinsuranceContract
import isleconfig
import genericclasses


class InsuranceFirm(MetaInsuranceOrg):
    """ReinsuranceFirm class.
       Inherits from MetaInsuranceFirm."""

    def __init__(self, simulation_parameters, agent_parameters):
        """Constructor method.
               Accepts arguments
                   Signature is identical to constructor method of parent class.
           Constructor calls parent constructor and only overwrites boolean indicators of insurer and reinsurer role of
           the object."""
        super().__init__(simulation_parameters, agent_parameters)
        self.is_insurer = True
        self.is_reinsurer = False

    def adjust_dividends(self, time: int, actual_capacity: float):
        """Method to adjust dividends firm pays to investors.
            Accepts:
                time: Type Integer. Not used.
                actual_capacity: Type Decimal.
            No return values.
        Method is called from MetaInsuranceOrg iterate method between evaluating reinsurance and insurance risks to
        calculate dividend to be payed if the firm has made profit and has achieved capital targets."""

        profits = self.get_profitslosses()
        self.per_period_dividend = max(0, self.dividend_share_of_profits * profits)
        # max function ensures that no negative dividends are paid
        if actual_capacity < self.capacity_target:
            # no dividends if firm misses capital target
            self.per_period_dividend = 0

    def get_reinsurance_var_estimate(self, max_var: float) -> float:
        """Method to estimate the VaR if another reinsurance contract were to be taken.
            Accepts:
                max_var: Type Decimal. Max value at risk
            Returns:
                reinsurance_VaR_estimate: Type Decimal.
        This method takes the max VaR and mulitiplies it by a factor that estimates the VaR if another reinsurance
        contract was to be taken. Called by the adjust_target_capacity and get_capacity methods."""
        reinsurance_factor_estimate = (
            len(
                [
                    1
                    for categ_id in range(self.simulation_no_risk_categories)
                    if (self.category_reinsurance[categ_id] is None)
                ]
            )
            * 1.0
            / self.simulation_no_risk_categories
        ) * (1.0 - self.np_reinsurance_deductible_fraction)
        reinsurance_var_estimate = max_var * (1.0 + reinsurance_factor_estimate)
        return reinsurance_var_estimate

    def adjust_capacity_target(self, max_var: float):
        """Method to adjust capacity target.
                   Accepts:
                       max_var: Type Decimal.
                   No return values.
               This method decides to increase/decrease the capacity target dependant on if the ratio of
                capacity target to max VaR is above/below a predetermined limit."""
        reinsurance_var_estimate = self.get_reinsurance_var_estimate(max_var)
        if max_var + reinsurance_var_estimate == 0:
            # TODO: why is this being called with max_var = 0 anyway?
            capacity_target_var_ratio_estimate = float("inf")
        else:
            capacity_target_var_ratio_estimate = (
                (self.capacity_target + reinsurance_var_estimate)
                * 1.0
                / (max_var + reinsurance_var_estimate)
            )
        if (
            capacity_target_var_ratio_estimate
            > self.capacity_target_increment_threshold
        ):
            self.capacity_target *= self.capacity_target_increment_factor
        elif (
            capacity_target_var_ratio_estimate
            < self.capacity_target_decrement_threshold
        ):
            self.capacity_target *= self.capacity_target_decrement_factor

    def get_capacity(self, max_var: float) -> float:
        """Method to get capacity of firm.
                    Accepts:
                        max_var: Type Decimal.
                    Returns:
                        self.cash (+ reinsurance_VaR_estimate): Type Decimal.
                This method is called by increase_capacity to get the real capacity of the firm. If the firm has
                enough money to cover its max value at risk then its capacity is its cash + the reinsurance VaR
                estimate, otherwise the firm is recovering from some losses and so capacity is just cash."""
        if max_var < self.cash:
            reinsurance_var_estimate = self.get_reinsurance_var_estimate(max_var)
            return self.cash + reinsurance_var_estimate
        else:
            # (This point is only reached when insurer is in severe financial difficulty.
            # Ensure insurer recovers complete coverage.)
            return self.cash

    def increase_capacity(self, time: int, max_var: float) -> float:
        """Method to increase the capacity of the firm.
            Accepts:
                time: Type Integer.
                max_var: Type Decimal.
            Returns:
                capacity: Type Decimal.
        This method is called from the main iterate method in metainsuranceorg and gets prices for cat bonds and
        reinsurance then checks if each category needs it. Passes a random category and the prices to the
        increase_capacity_by_category method. If a firms capacity is above its target then it will only issue one if the
        market premium is above its average premium, otherwise firm is 'forced' to get a catbond or reinsurance. Only
        implemented for non-proportional(excess of loss) reinsurance. Only issues one reinsurance or catbond per
        iteration unless not enough capacity to meet target."""
        assert self.simulation_reinsurance_type == "non-proportional"
        """get prices"""
        reinsurance_price = self.simulation.get_reinsurance_premium(
            self.np_reinsurance_deductible_fraction
        )
        cat_bond_price = self.simulation.get_cat_bond_price(
            self.np_reinsurance_deductible_fraction
        )
        capacity = None
        if not reinsurance_price == cat_bond_price == float("inf"):
            categ_ids = [
                categ_id
                for categ_id in range(self.simulation_no_risk_categories)
                if (self.category_reinsurance[categ_id] is None)
            ]
            if len(categ_ids) > 1:
                np.random.shuffle(categ_ids)
            while len(categ_ids) >= 1:
                categ_id = categ_ids.pop()
                capacity = self.get_capacity(max_var)
                if (
                    self.capacity_target < capacity
                ):  # just one per iteration, unless capital target is unmatched
                    if self.increase_capacity_by_category(
                        time,
                        categ_id,
                        reinsurance_price=reinsurance_price,
                        cat_bond_price=cat_bond_price,
                        force=False,
                    ):
                        categ_ids = []
                else:
                    self.increase_capacity_by_category(
                        time,
                        categ_id,
                        reinsurance_price=reinsurance_price,
                        cat_bond_price=cat_bond_price,
                        force=True,
                    )
        # capacity is returned in order not to recompute more often than necessary
        if capacity is None:
            capacity = self.get_capacity(max_var)
        return capacity

    def increase_capacity_by_category(
        self,
        time: int,
        categ_id: int,
        reinsurance_price: float,
        cat_bond_price: float,
        force: bool = False,
    ) -> bool:
        """Method to increase capacity. Only called by increase_capacity.
            Accepts:
                time: Type Integer
                categ_id: Type integer.
                reinsurance_price: Type Decimal.
                cat_bond_price: Type Decimal.
                force: Type Boolean. Forces firm to get reinsurance/catbond or not.
            Returns Boolean to stop loop if firm has enough capacity.
        This method is given a category and prices of reinsurance/catbonds and will issue whichever one is cheaper to a
        firm for the given category. This is forced if firm does not have enough capacity to meet target otherwise will
        only issue if market premium is greater than firms average premium."""
        if isleconfig.verbose:
            print(
                f"IF {self.id:d} increasing capacity in period {time:d}, cat bond price: {cat_bond_price:f},"
                f" reinsurance premium {reinsurance_price:f}"
            )
        if not force:
            actual_premium = self.get_average_premium(categ_id)
            possible_premium = self.simulation.get_market_premium()
            if actual_premium >= possible_premium:
                return False
        """on the basis of prices decide for obtaining reinsurance or for issuing cat bond"""
        if reinsurance_price > cat_bond_price:
            if isleconfig.verbose:
                print(f"IF {self.id:d} issuing Cat bond in period {time:d}")
            self.issue_cat_bond(time, categ_id)
        else:
            if isleconfig.verbose:
                print(f"IF {self.id:d} getting reinsurance in period {time:d}")
            self.ask_reinsurance_non_proportional_by_category(time, categ_id)
        return True

    def get_average_premium(self, categ_id: int) -> float:
        """Method to calculate and return the firms average premium for all currently underwritten contracts.
            Accepts:
                categ_id: Type Integer.
            Returns:
                premium payments left/total value of contracts: Type Decimal"""
        weighted_premium_sum = 0
        total_weight = 0
        for contract in self.underwritten_contracts:
            if contract.category == categ_id:
                total_weight += contract.value
                contract_premium = contract.periodized_premium * contract.runtime
                weighted_premium_sum += contract_premium
        if total_weight == 0:
            return 0  # will prevent any attempt to reinsure empty categories
        return weighted_premium_sum * 1.0 / total_weight

    def ask_reinsurance(self, time: int):
        """Method called specifically to call relevant reinsurance function for simulations reinsurance type. Only
           non-proportional type is used as this is the one mainly used in reality.
            Accepts:
                time: Type Integer.
            No return values."""
        if self.simulation_reinsurance_type == "proportional":
            self.ask_reinsurance_proportional()
        elif self.simulation_reinsurance_type == "non-proportional":
            self.ask_reinsurance_non_proportional(time)
        else:
            raise ValueError(
                f"Undefined reinsurance type {self.simulation_reinsurance_type}"
            )

    def ask_reinsurance_non_proportional(self, time: int):
        """ Method for requesting excess of loss reinsurance for all underwritten contracts by category.
            The method calculates the combined value at risk. With a probability it then creates a combined
            reinsurance risk that may then be underwritten by a reinsurance firm.
            Arguments: 
                time: integer
            Returns None."""
        """Evaluate by risk category"""
        for categ_id in range(self.simulation_no_risk_categories):
            """Seek reinsurance only with probability 10% if not already reinsured"""
            # QUERY It doesn't actually have the 10% chance?
            # TODO: find a more generic way to decide whether to request reinsurance for category in this period
            if self.category_reinsurance[categ_id] is None:
                self.ask_reinsurance_non_proportional_by_category(time, categ_id)

    def characterize_underwritten_risks_by_category(
        self, categ_id: int
    ) -> Tuple[float, float, int, float]:
        """Method to characterise associated risks in a given category in terms of value, number, avg risk factor, and
        total premium per iteration.
            Accepts:
                categ_id: Type Integer. The given category for characterising risks.
            Returns:
                total_value: Type Decimal. Total value of all contracts in the category.
                avg_risk_facotr: Type Decimal. Avg risk factor of all contracted risks in category.
                number_risks: Type Integer. Total number of contracted risks in category.
                periodised_total_premium: Total value per month of all contracts premium payments."""
        total_value = 0
        avg_risk_factor = 0
        number_risks = 0
        periodized_total_premium = 0
        for contract in self.underwritten_contracts:
            if contract.category == categ_id:
                total_value += contract.value
                avg_risk_factor += contract.risk_factor
                number_risks += 1
                periodized_total_premium += contract.periodized_premium
        if number_risks > 0:
            avg_risk_factor /= number_risks
        return total_value, avg_risk_factor, number_risks, periodized_total_premium

    def ask_reinsurance_non_proportional_by_category(
        self, time: int, categ_id: int, purpose: str = "newrisk"
    ) -> Optional[genericclasses.RiskProperties]:
        """Method to create a reinsurance risk for a given category for firm that calls it. Called from increase_
        capacity_by_category, ask_reinsurance_non_proportional, and roll_over in metainsuranceorg.
            Accepts:
                time: Type Integer.
                categ_id: Type Integer.
                purpose: Type String. Needed for when called from roll_over method as the risk is then returned.
            Returns:
                risk: Type DataDict. Only returned when method used for roll_over.
        This method is given a category, then characterises all the underwritten risks in that category for the firm
        and, assuming firms has underwritten risks in category, creates new reinsurance risk with values based on firms
        existing underwritten risks. If the method was called to create a new risks then it is appended to list of
        'reinrisks', otherwise used for creating the risk when a reinsurance contract rolls over."""
        [
            total_value,
            avg_risk_factor,
            number_risks,
            periodized_total_premium,
        ] = self.characterize_underwritten_risks_by_category(categ_id)
        if number_risks > 0:
            risk = genericclasses.RiskProperties(
                value=total_value,
                category=categ_id,
                owner=self,
                insurancetype="excess-of-loss",
                number_risks=number_risks,
                deductible_fraction=self.np_reinsurance_deductible_fraction,
                excess_fraction=self.np_reinsurance_excess_fraction,
                periodized_total_premium=periodized_total_premium,
                runtime=12,
                expiration=time + 12,
                risk_factor=avg_risk_factor,
            )  # TODO: make runtime into a parameter
            if purpose == "newrisk":
                self.simulation.append_reinrisks(risk)
            elif purpose == "rollover":
                return risk
        elif number_risks == 0 and purpose == "rollover":
            return None

    def ask_reinsurance_proportional(self):
        """Method to create proportional reinsurance risk. Not used in code as not really used in reality.
                    No accepted values.
                    No return values."""
        nonreinsured = [
            contract
            for contract in self.underwritten_contracts
            if contract.reincontract is None
        ]

        nonreinsured.reverse()

        if len(nonreinsured) >= (1 - self.reinsurance_limit) * len(
            self.underwritten_contracts
        ):
            counter = 0
            limitrein = len(nonreinsured) - (1 - self.reinsurance_limit) * len(
                self.underwritten_contracts
            )
            for contract in nonreinsured:
                if counter < limitrein:
                    risk = genericclasses.RiskProperties(
                        value=contract.value,
                        category=contract.category,
                        owner=self,
                        reinsurance_share=1.0,
                        expiration=contract.expiration,
                        contract=contract,
                        risk_factor=contract.risk_factor,
                    )

                    self.simulation.append_reinrisks(risk)
                    counter += 1
                else:
                    break

    def add_reinsurance(
        self,
        category: int,
        excess_fraction: float,
        deductible_fraction: float,
        contract: ReinsuranceContract,
    ):
        """Method called by reinsurancecontract to add the reinsurance contract to the firms counter for the given
        category, normally used so only one reinsurance contract is issued per category at a time.
            Accepts:
                category: Type Integer.
                excess_fraction: Type Decimal. Value of excess.
                deductible_fraction: Type Decimal. Value of deductible.
                contract: Type Class. Reinsurance contract issued to firm.
            No return values."""
        self.riskmodel.add_reinsurance(
            category, excess_fraction, deductible_fraction, contract
        )
        self.category_reinsurance[category] = contract

    def delete_reinsurance(self, category: int, contract: ReinsuranceContract):
        """Method called by reinsurancecontract to delete the reinsurance contract from the firms counter for the given
        category, used so that another reinsurance contract can be issued for that category if needed.
            Accepts:
                category: Type Integer.
                contract: Type Class. Reinsurance contract issued to firm.
            No return values."""
        self.riskmodel.delete_reinsurance(category, contract)
        self.category_reinsurance[category] = None

    def issue_cat_bond(
        self, time: int, categ_id: int, per_value_per_period_premium: int = 0
    ):
        """Method to issue cat bond to given firm for given category.
            Accepts:
                time: Type Integer.
                categ_id: Type Integer.
                per_value_per_period_premium: Type Integer.
            No return values.
        Method is only called by increase_capacity_by_category method when CatBond prices are lower than reinsurance. It
        then creates the CatBond as a quasi-reinsurance contract that is paid for immediately (by simulation) with no
        premium payments."""
        [
            total_value,
            avg_risk_factor,
            number_risks,
            _,
        ] = self.characterize_underwritten_risks_by_category(categ_id)
        if number_risks > 0:
            # TODO: make runtime into a parameter
            risk = genericclasses.RiskProperties(
                value=total_value,
                category=categ_id,
                owner=self,
                insurancetype="excess-of-loss",
                number_risks=number_risks,
                deductible_fraction=self.np_reinsurance_deductible_fraction,
                excess_fraction=self.np_reinsurance_excess_fraction,
                periodized_total_premium=0,
                runtime=12,
                expiration=time + 12,
                risk_factor=avg_risk_factor,
            )

            _, _, var_this_risk, _ = self.riskmodel.evaluate([], self.cash, risk)
            per_period_premium = per_value_per_period_premium * risk.value
            total_premium = sum(
                [
                    per_period_premium * ((1 / (1 + self.interest_rate)) ** i)
                    for i in range(risk.runtime)
                ]
            )  # TODO: or is it range(1, risk["runtime"]+1)?
            # catbond = CatBond(self.simulation, per_period_premium)
            # TODO: shift obtain_yield method to insurancesimulation, thereby making it unnecessary to drag
            #  parameters like self.interest_rate from instance to instance and from class to class
            new_catbond = catbond.CatBond(
                self.simulation, per_period_premium, self.interest_rate
            )

            """add contract; contract is a quasi-reinsurance contract"""
            contract = ReinsuranceContract(
                new_catbond,
                risk,
                time,
                0,
                risk.runtime,
                self.default_contract_payment_period,
                expire_immediately=self.simulation_parameters["expire_immediately"],
                initial_var=var_this_risk,
                insurancetype=risk.insurancetype,
            )
            # per_value_reinsurance_premium = 0 because the insurance firm make only one payment to catbond

            new_catbond.set_contract(contract)
            """sell cat bond (to self.simulation)"""
            self.simulation.receive_obligation(var_this_risk, self, time, "bond")
            new_catbond.set_owner(self.simulation)
            """hand cash over to cat bond such that var_this_risk is covered"""
            obligation = genericclasses.Obligation(
                amount=var_this_risk + total_premium,
                recipient=new_catbond,
                due_time=time,
                purpose="bond",
            )
            self._pay(obligation)  # TODO: is var_this_risk the correct amount?
            """register catbond"""
            self.simulation.add_agents(catbond.CatBond, "catbond", [new_catbond])

    def make_reinsurance_claims(self, time: int):
        """Method to make reinsurance claims.
            Accepts:
                time: Type Integer.
            No return values.
        This method calculates the total amount of claims this iteration per category, and explodes (see reinsurance
        contracts) any reinsurance contracts present for one of the contracts (currently always zero). Then, for a
        category with reinsurance and claims, the applicable reinsurance contract is exploded."""
        # TODO: reorganize this with risk category ledgers
        # TODO: Put facultative insurance claims here
        claims_this_turn = np.zeros(self.simulation_no_risk_categories)
        for contract in self.underwritten_contracts:
            categ_id, claims, is_proportional = contract.get_and_reset_current_claim()
            if is_proportional:
                claims_this_turn[categ_id] += claims
            if contract.reincontract:
                contract.reincontract.explode(time, damage_extent=claims)

        for categ_id in range(self.simulation_no_risk_categories):
            if (
                claims_this_turn[categ_id] > 0
                and self.category_reinsurance[categ_id] is not None
            ):
                self.category_reinsurance[categ_id].explode(
                    time, damage_extent=claims_this_turn[categ_id]
                )

    def get_excess_of_loss_reinsurance(self) -> MutableSequence[Mapping]:
        """Method to return list containing the reinsurance for each category interms of the reinsurer, value of
        contract and category. Only used for network visualisation.
            No accepted values.
            Returns:
                reinsurance: Type list of DataDicts."""
        reinsurance = []
        for categ_id in range(self.simulation_no_risk_categories):
            if self.category_reinsurance[categ_id] is not None:
                reinsurance_contract = {}
                reinsurance_contract["reinsurer"] = self.category_reinsurance[
                    categ_id
                ].insurer
                reinsurance_contract["value"] = self.category_reinsurance[
                    categ_id
                ].value
                reinsurance_contract["category"] = categ_id
                reinsurance.append(reinsurance_contract)
        return reinsurance

    def create_reinrisk(
        self, time: int, categ_id: int
    ) -> Optional[genericclasses.RiskProperties]:
        """Proceed with creation of reinsurance risk only if category is not empty."""
        [
            total_value,
            avg_risk_factor,
            number_risks,
            periodized_total_premium,
        ] = self.characterize_underwritten_risks_by_category(categ_id)
        if number_risks > 0:
            # TODO: make runtime into a parameter
            risk = genericclasses.RiskProperties(
                value=total_value,
                category=categ_id,
                owner=self,
                insurancetype="excess-of-loss",
                number_risks=number_risks,
                deductible_fraction=self.np_reinsurance_deductible_fraction,
                excess_fraction=self.np_reinsurance_excess_fraction,
                periodized_total_premium=periodized_total_premium,
                runtime=12,
                expiration=time + 12,
                risk_factor=avg_risk_factor,
            )
            return risk
        else:
            return None


class ReinsuranceFirm(InsuranceFirm):
    """ReinsuranceFirm class.
       Inherits from InsuranceFirm."""

    def __init__(self, simulation_parameters, agent_parameters):
        """Constructor method.
               Accepts arguments
                   Signature is identical to constructor method of parent class.
           Constructor calls parent constructor and only overwrites boolean indicators of insurer and reinsurer role of
           the object."""
        super().__init__(simulation_parameters, agent_parameters)
        self.is_insurer = False
        self.is_reinsurer = True
