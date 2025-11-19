from dataclasses import dataclass

@dataclass
class PIDGains:
    kp: float = 0.08
    ki: float = 0.02
    kd: float = 0.04

class PID:
    def __init__(self, gains: PIDGains, umin=0, umax=1, tau=0.05, bias=0):
        self.kp = gains.kp
        self.ki = gains.ki
        self.kd = gains.kd
        self.umin = umin
        self.umax = umax
        self.tau = max(1e-6, tau)
        self.bias = bias
        self.reset()

    def reset(self):
        self._i = 0
        self._prev_pv = None
        self._d_filt = 0
        self.u = 0

    def set_gains(self, kp=None, ki=None, kd=None):
        if kp is not None: self.kp = max(0, kp)
        if ki is not None: self.ki = max(0, ki)
        if kd is not None: self.kd = max(0, kd)

    def step(self, setpoint: float, pv: float, dt: float) -> float:
        if dt <= 0:
            return self.u
        e = setpoint - pv
        p = self.kp * e
        d_raw = 0
        if self._prev_pv is not None:
            d_meas = (pv - self._prev_pv) / dt
            d_raw = -self.kd * d_meas
            alpha = dt / (self.tau + dt)
            self._d_filt += alpha * (d_raw - self._d_filt)
        self._prev_pv = pv
        d = self._d_filt
        i_cand = self._i + self.ki * e * dt
        u_sin = self.bias + p + i_cand + d
        u = max(self.umin, min(self.umax, u_sin))
        if not ((u_sin > self.umax and e > 0) or (u_sin < self.umin and e < 0)):
            self._i = i_cand
        self.u = u
        return self.u
