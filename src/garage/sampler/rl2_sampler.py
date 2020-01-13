"""BatchSampler which uses VecEnvExecutor to run multiple environments."""
import itertools
import pickle
import time
from collections import OrderedDict

from dowel import logger, tabular
import numpy as np

from garage.experiment import deterministic
from garage.misc import tensor_utils
from garage.misc.prog_bar_counter import ProgBarCounter
from garage.sampler.batch_sampler import BatchSampler
from garage.sampler.stateful_pool import singleton_pool
from garage.sampler.utils import truncate_paths
from garage.sampler.vec_env_executor import VecEnvExecutor


class RL2Sampler(BatchSampler):
    """BatchSampler which uses VecEnvExecutor to run multiple environments.

    This sampler is specific for RL^2. See https://arxiv.org/pdf/1611.02779.pdf.

    Args:
        algo (garage.np.algos.RLAlgorithm): An algorithm instance.
        env (garage.envs.GarageEnv): An environement instance.
        n_envs (int): Number of environment instances to setup.
            This parameter has effect on sampling performance.

    """

    def __init__(self,
                 algo,
                 env,
                 meta_batch_size,
                 episode_per_task,
                 n_envs=None):
        if n_envs is None:
            n_envs = singleton_pool.n_parallel * 4
        super().__init__(algo, env)
        self._n_envs = n_envs

        self._meta_batch_size = meta_batch_size
        self._episode_per_task = episode_per_task
        self._vec_env = None
        self._env_spec = self.env.spec

    def start_worker(self):
        """Start workers."""
        n_envs = self._n_envs
        assert n_envs >= self._meta_batch_size, 'Number of vectorized environments'
        ' should be at least meta_batch_size.'
        assert n_envs % self._meta_batch_size == 0, 'Number of vectorized'
        ' environments should be a multiple of meta_batch_size.'
        envs_per_worker = n_envs // self._meta_batch_size

        tasks = self.env.sample_tasks(self._meta_batch_size)
        vec_envs = []
        for task in tasks:
            vec_env = pickle.loads(pickle.dumps(self.env))
            vec_env.set_task(task)
            vec_envs.extend([vec_env for _ in range(envs_per_worker)])
        # Deterministically set environment seeds based on the global seed.
        seed0 = deterministic.get_seed()
        if seed0 is not None:
            for (i, e) in enumerate(vec_envs):
                e.seed(seed0 + i)

        self._vec_env = VecEnvExecutor(
            envs=vec_envs, max_path_length=self.algo.max_path_length)

    def shutdown_worker(self):
        """Shutdown workers."""
        self._vec_env.close()

    # pylint: disable=too-many-statements
    def obtain_samples(self, itr, batch_size=None, whole_paths=True):
        """Sample the policy for new trajectories.

        Args:
            itr (int): Iteration number.
            batch_size (int): Number of samples to be collected. If None,
                it will be default [algo.max_path_length * n_envs].
            whole_paths (bool): Whether return all the paths or not. True
                by default. It's possible for the paths to have total actual
                sample size larger than batch_size, and will be truncated if
                this flag is true.

        Returns:
            list[dict]: Sample paths.

        Note:
            Each path is a dictionary, with keys and values as following:
                * observations: numpy.ndarray with shape [Batch, *obs_dims]
                * actions: numpy.ndarray with shape [Batch, *act_dims]
                * rewards: numpy.ndarray with shape [Batch, ]
                * env_infos: A dictionary with each key representing one
                  environment info, value being a numpy.ndarray with shape
                  [Batch, ?]. One example is "ale.lives" for atari
                  environments.
                * agent_infos: A dictionary with each key representing one
                  agent info, value being a numpy.ndarray with shape
                  [Batch, ?]. One example is "prev_action", which is used
                  for recurrent policy as previous action input, merged with
                  the observation input as the state input.

        """
        logger.log('Obtaining samples for iteration %d...' % itr)

        if batch_size is None:
            batch_size = self._episode_per_task * self.algo.max_path_length * self._n_envs

        paths = OrderedDict()
        for i in range(self._n_envs):
            paths[i] = []

        n_samples = 0
        obses = self._vec_env.reset()
        dones = np.asarray([True] * self._vec_env.num_envs)
        running_paths = [None] * self._vec_env.num_envs

        pbar = ProgBarCounter(batch_size)
        policy_time = 0
        env_time = 0
        process_time = 0

        policy = self.algo.policy
        # Only reset policies at the beginning of a meta batch (or a "trial", as mentioned in paper)
        policy.reset(dones)

        while n_samples < batch_size:
            t = time.time()

            actions, agent_infos = policy.get_actions(obses)

            policy_time += time.time() - t
            t = time.time()
            next_obses, rewards, dones, env_infos = self._vec_env.step(actions)
            # self._vec_env.envs[0].render()
            env_time += time.time() - t
            t = time.time()

            agent_infos = tensor_utils.split_tensor_dict_list(agent_infos)
            env_infos = tensor_utils.split_tensor_dict_list(env_infos)
            if env_infos is None:
                env_infos = [dict() for _ in range(self._vec_env.num_envs)]
            if agent_infos is None:
                agent_infos = [dict() for _ in range(self._vec_env.num_envs)]
            for idx, observation, action, reward, env_info, agent_info, done in zip(  # noqa: E501
                    itertools.count(), obses, actions, rewards, env_infos,
                    agent_infos, dones):
                if running_paths[idx] is None:
                    running_paths[idx] = dict(
                        observations=[],
                        actions=[],
                        rewards=[],
                        dones=[],
                        env_infos=[],
                        agent_infos=[],
                    )
                running_paths[idx]['observations'].append(observation)
                running_paths[idx]['actions'].append(action)
                running_paths[idx]['rewards'].append(reward)
                running_paths[idx]['dones'].append(done)
                running_paths[idx]['env_infos'].append(env_info)
                running_paths[idx]['agent_infos'].append(agent_info)
                if done:
                    obs = np.asarray(running_paths[idx]['observations'])
                    actions = np.asarray(running_paths[idx]['actions'])
                    paths[idx].append(
                        dict(observations=obs,
                             actions=actions,
                             rewards=np.asarray(running_paths[idx]['rewards']),
                             dones=np.asarray(running_paths[idx]['dones']),
                             env_infos=tensor_utils.stack_tensor_dict_list(
                                 running_paths[idx]['env_infos']),
                             agent_infos=tensor_utils.stack_tensor_dict_list(
                                 running_paths[idx]['agent_infos'])))
                    n_samples += len(running_paths[idx]['rewards'])
                    running_paths[idx] = None
            process_time += time.time() - t
            pbar.inc(len(obses))
            obses = next_obses

        pbar.stop()

        tabular.record('PolicyExecTime', policy_time)
        tabular.record('EnvExecTime', env_time)
        tabular.record('ProcessExecTime', process_time)

        return paths if whole_paths else truncate_paths(paths, batch_size)