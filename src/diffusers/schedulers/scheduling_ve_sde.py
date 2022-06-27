# Copyright 2022 UC Berkely Team and The HuggingFace Team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# DISCLAIMER: This file is strongly influenced by https://github.com/ermongroup/ddim

import numpy as np
import torch

from ..configuration_utils import ConfigMixin
from .scheduling_utils import SchedulerMixin


class VeSdeScheduler(SchedulerMixin, ConfigMixin):
    def __init__(self, snr=0.15, sigma_min=0.01, sigma_max=1348, N=2, sampling_eps=1e-5, tensor_format="np"):
        super().__init__()
        self.register_to_config(
            snr=snr,
            sigma_min=sigma_min,
            sigma_max=sigma_max,
            N=N,
            sampling_eps=sampling_eps,
        )
        # (PVP) - clean up with .config.
        self.sigma_min = sigma_min
        self.sigma_max = sigma_max
        self.snr = snr
        self.N = N
        self.discrete_sigmas = torch.exp(torch.linspace(np.log(self.sigma_min), np.log(self.sigma_max), N))
        self.timesteps = torch.linspace(1, sampling_eps, N)

    def get_sigma_t(self, t):
        return self.sigma_min * (self.sigma_max / self.sigma_min) ** self.timesteps[t]

    def step_pred(self, result, x, t):
        t = self.timesteps[t] * torch.ones(x.shape[0], device=x.device)

        timestep = (t * (self.N - 1)).long()
        sigma = self.discrete_sigmas.to(t.device)[timestep]
        adjacent_sigma = torch.where(
            timestep == 0, torch.zeros_like(t), self.discrete_sigmas[timestep - 1].to(t.device)
        )
        f = torch.zeros_like(x)
        G = torch.sqrt(sigma**2 - adjacent_sigma**2)

        f = f - G[:, None, None, None] ** 2 * result

        z = torch.randn_like(x)
        x_mean = x - f
        x = x_mean + G[:, None, None, None] * z
        return x, x_mean

    def step_correct(self, result, x):
        noise = torch.randn_like(x)
        grad_norm = torch.norm(result.reshape(result.shape[0], -1), dim=-1).mean()
        noise_norm = torch.norm(noise.reshape(noise.shape[0], -1), dim=-1).mean()
        step_size = (self.snr * noise_norm / grad_norm) ** 2 * 2
        step_size = step_size * torch.ones(x.shape[0], device=x.device)
        x_mean = x + step_size[:, None, None, None] * result

        x = x_mean + torch.sqrt(step_size * 2)[:, None, None, None] * noise

        return x