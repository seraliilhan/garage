"""This script is a test that fails when MAML-TRPO performance is too low."""
import pytest
try:
    # pylint: disable=unused-import
    import mujoco_py  # noqa: F401
except Exception:  # pylint: disable=broad-except
    pytest.skip(allow_module_level=True)
import torch

from garage.envs import normalize
from garage.envs.base import GarageEnv
from garage.envs.mujoco import HalfCheetahDirEnv
from garage.experiment import deterministic, LocalRunner
from garage.np.baselines import LinearFeatureBaseline
from garage.torch.algos import MAMLPPO
from garage.torch.policies import GaussianMLPPolicy
from tests.fixtures import snapshot_config


class TestMAMLPPO:
    """Test class for MAML-PPO."""

    def setup_method(self):
        """Setup method which is called before every test."""
        self.env = GarageEnv(
            normalize(HalfCheetahDirEnv(), expected_action_scale=10.))
        self.policy = GaussianMLPPolicy(
            env_spec=self.env.spec,
            hidden_sizes=(64, 64),
            hidden_nonlinearity=torch.tanh,
            output_nonlinearity=None,
        )
        self.baseline = LinearFeatureBaseline(env_spec=self.env.spec)

    def teardown_method(self):
        """Teardown method which is called after every test."""
        self.env.close()

    def test_ppo_pendulum(self):
        """Test PPO with Pendulum environment."""
        deterministic.set_seed(0)

        rollouts_per_task = 5
        max_path_length = 100

        runner = LocalRunner(snapshot_config)
        algo = MAMLPPO(env=self.env,
                       policy=self.policy,
                       baseline=self.baseline,
                       max_path_length=max_path_length,
                       meta_batch_size=5,
                       discount=0.99,
                       gae_lambda=1.,
                       inner_lr=0.1,
                       num_grad_updates=1)

        runner.setup(algo, self.env)
        last_avg_ret = runner.train(n_epochs=10,
                                    batch_size=rollouts_per_task *
                                    max_path_length)

        assert last_avg_ret > -5
