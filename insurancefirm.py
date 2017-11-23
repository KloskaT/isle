from firm import Firm

class InsuranceFirm(Firm):
    """ReinsuranceFirm class.
       Inherits from InsuranceFirm."""
    def init(self, simulation_parameters, agent_parameters):
        """Constructor method.
               Accepts arguments
                   Signature is identical to constructor method of parent class.
           Constructor calls parent constructor and only overwrites boolean indicators of insurer and reinsurer role of
           the object."""
        super(InsuranceFirm, self).init(simulation_parameters, agent_parameters)
        self.is_insurer = True
        self.is_reinsurer = False


