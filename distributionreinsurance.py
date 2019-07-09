import functools
import numpy as np
import scipy.stats


class ReinsuranceDistWrapper:
    # QUERY: Is this the distribution of the risk when excess of loss reinsurance is applied?
    def __init__(self, dist, lower_bound=None, upper_bound=None):
        assert lower_bound is not None or upper_bound is not None
        self.dist = dist
        self.lower_bound = lower_bound
        self.upper_bound = upper_bound
        if lower_bound is None:
            self.lower_bound = -np.inf
        elif upper_bound is None:
            self.upper_bound = np.inf
        assert self.upper_bound > self.lower_bound
        self.redistributed_share = dist.cdf(upper_bound) - dist.cdf(lower_bound)

    @functools.lru_cache(maxsize=512)
    def pdf(self, x):
        x = np.array(x, ndmin=1)
        r = map(
            lambda Y: self.dist.pdf(Y)
            if Y < self.lower_bound
            else np.inf
            if Y == self.lower_bound
            else self.dist.pdf(Y + self.upper_bound - self.lower_bound),
            x,
        )
        r = np.array(list(r))
        if len(r.flatten()) == 1:
            r = float(r)
        return r

    @functools.lru_cache(maxsize=512)
    def cdf(self, x):
        x = np.array(x, ndmin=1)
        r = map(
            lambda Y: self.dist.cdf(Y)
            if Y < self.lower_bound
            else self.dist.cdf(Y + self.upper_bound - self.lower_bound),
            x,
        )
        r = np.array(list(r))
        if len(r.flatten()) == 1:
            r = float(r)
        return r

    @functools.lru_cache(maxsize=512)
    def ppf(self, x):
        x = np.array(x, ndmin=1)
        assert (x >= 0).all() and (x <= 1).all()
        r = map(
            lambda Y: self.dist.ppf(Y)
            if Y <= self.dist.cdf(self.lower_bound)
            else self.dist.ppf(self.dist.cdf(self.lower_bound))
            if Y <= self.dist.cdf(self.upper_bound)
            else self.dist.ppf(Y) - self.upper_bound + self.lower_bound,
            x,
        )
        r = np.array(list(r))
        if len(r.flatten()) == 1:
            r = float(r)
        return r

    def rvs(self, size=1):
        sample = self.dist.rvs(size=size)
        sample1 = sample[sample <= self.lower_bound]
        sample2 = sample[sample > self.lower_bound]
        sample3 = sample2[sample2 >= self.upper_bound]
        sample2 = sample2[sample2 < self.upper_bound]

        sample2 = np.ones(len(sample2)) * self.lower_bound
        sample3 = sample3 - self.upper_bound + self.lower_bound

        sample = np.append(np.append(sample1, sample2), sample3)
        return sample[:size]


if __name__ == "__main__":
    non_truncated = scipy.stats.pareto(b=2, loc=0, scale=0.5)
    # truncated = ReinsuranceDistWrapper(lower_bound=0, upper_bound=1, dist=non_truncated)
    truncated = ReinsuranceDistWrapper(
        lower_bound=0.9, upper_bound=1.1, dist=non_truncated
    )

    x1 = np.linspace(non_truncated.ppf(0.01), non_truncated.ppf(0.99), 100)
    x2 = np.linspace(truncated.ppf(0.01), truncated.ppf(0.99), 100)

    # pdb.set_trace()
