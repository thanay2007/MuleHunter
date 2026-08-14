"""Detection tiers: rules, gradient boosting, graph neural network.

All three are kept and all three are reported. Detection is an *input* to this
system, not its output -- the interdiction solver consumes `p_mule` and decides
what to do about it. Keeping the weak tier visible is what makes that argument
checkable rather than asserted.
"""
