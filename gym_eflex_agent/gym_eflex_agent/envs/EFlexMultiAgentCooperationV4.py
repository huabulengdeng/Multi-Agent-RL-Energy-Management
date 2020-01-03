from enum import Enum

import gym
import math
import numpy as np
import yaml
from gym import spaces
from gym.utils import seeding

MAX_PRODUCTION_STEP = 20


class EFLEXAgentState(Enum):
    Aborted = 1
    Stopped = 0
    PowerOff = 2
    LoadChange = 3
    StandBy = 4
    StartedUp = 5
    Idle = 6
    Execute = 7
    Completed = 8
    Held = 9
    Suspended = 10


class EFLEXAgentTransition(Enum):
    SC = 0
    Abort = 1
    Clear = 2
    Reset = 3
    Stop = 4
    ChangeLoad = 5
    Hold = 6
    PowerOn = 7
    PowerOff = 8
    Standby = 9
    Start = 10
    Suspend = 11
    UnHold = 12
    Unsuspend = 13


class EFLEXAgentEnvironmentException(Exception):
    """
    Related to errors with sending actions.
    """
    pass


class TOUGenerator:

    def __init__(self, tou_conf):

        # Simulation related variables.
        self.type = tou_conf['type']
        self.steps = tou_conf['steps']
        self.values = tou_conf['values']
        self.current_step = 0
        self.current_tou_value = self.values[0]
        self.np_random = None

    def step(self):
        """
        Returns
        -------
            current_tou_value (float) :
                current TOU Price.
        """

        self.current_step = self.current_step + 1
        for i, limit in enumerate(self.steps):
            if self.current_step > limit:
                self.current_tou_value = self.values[i]
                continue
            else:
                break

        return self.current_tou_value

    def reset(self):
        # self.current_step = 0
        # self.current_tou_value = self.values[0]
        pass

    def seed(self, seed=None):
        self.np_random, seed = seeding.np_random(seed)
        return [seed]

    def close(self):
        pass


class LoadProfile:

    def __init__(self, load_conf):

        # Simulation related variables.
        self.type = load_conf['type']
        self.steps = load_conf['steps']
        self.values = load_conf['values']
        self.tolerance_factor = load_conf['tolerance_factor']
        self.current_step = 0
        self.current_max_load = self.values[0] * (1 + self.tolerance_factor)
        self.np_random = None

    def step(self):
        """
        Returns
        -------
            current_tou_value (float) :
                current TOU Price.
        """

        self.current_step = self.current_step + 1
        for i, limit in enumerate(self.steps):
            if self.current_step > limit:
                self.current_max_load = self.values[i] * (1 + self.tolerance_factor)
                continue
            else:
                break

        return self.current_max_load

    def reset(self):
        # self.current_step = 0
        # self.current_max_load = self.values[0] * (1 + self.tolerance_factor)
        pass

    def seed(self, seed=None):
        self.np_random, seed = seeding.np_random(seed)
        return [seed]

    def close(self):
        pass


class EFlexMultiAgentCooperationClsV4(gym.Env):
    metadata = {'render.modes': ['human']}

    def __init__(self):
        # action space specify which transition can be activated
        self.action_space = []  # spaces.Discrete(len(EFLEXAgentTransition))  # {0,1,...,n-1}

        # observation is a multi discrete specifying which state is activated
        self.observation_space = []  # spaces.MultiBinary(len(EFLEXAgentState))

        # reward_range
        self.reward_range = (float(-1.0), float(1.0))

        self.display = None
        self.seed_value = None

        # Simulation related variables.
        self.agent_configs = {}
        self.agents = []
        self.n = 0
        self.shared_reward = False

        # Eflex related variables
        self.max_allowed_power = 0
        self.energy_cost_budget = 0
        self.current_system_power = 0.0
        self.global_reward = 0.0
        self.current_winner = []

        # TOU generator
        self.tou_generator = None
        self.load_profile = None

    def configure(self, display=None, agent_config_path=None, shared_reward=False):
        self.shared_reward = shared_reward
        self.display = display
        if agent_config_path:
            self.agent_configs = self._load_config(agent_config_path)

        # Read the environment configurations
        env_config = self.agent_configs['environement_config']
        self.max_allowed_power = env_config['max_allowed_power']
        self.energy_cost_budget = env_config['energy_cost_budget']

        # Read TOU generator config
        tou_conf = env_config['tou_generartor']
        self.tou_generator = TOUGenerator(tou_conf=tou_conf)

        # Read load profile config
        load_profile_conf = env_config['load_profile']
        self.load_profile = LoadProfile(load_conf=load_profile_conf)

        for agent_name, agent_conf in self.agent_configs['agents'].items():
            current_agent = None
            # initialize the agents
            module_spec = self._import_module("gym_eflex_agent", agent_conf['type'])
            if module_spec is None:
                raise EFLEXAgentEnvironmentException("The environement  config contains an unknown agent type {}"
                                                     .format(agent_conf['type']))
            else:
                current_agent = module_spec(agent_conf, agent_name, self.max_allowed_power)
                self.agents.append(current_agent)

            # action space
            self.action_space.append(current_agent.action_space)

            # observation space
            self.observation_space.append(current_agent.observation_space)

        self.n = len(self.agents)
        self.seed(self.seed_value)
        self.reset()

    @staticmethod
    def _import_module(module_name, class_name):
        """Constructor"""

        macro_module = __import__(module_name)
        module0 = getattr(macro_module, 'envs')
        module = getattr(module0, 'EFlexMultiAgentCooperationV4')
        my_class = getattr(module, class_name)
        return my_class

    @staticmethod
    def _load_config(_trainer_config_path):
        try:
            with open(_trainer_config_path) as data_file:
                trainer_config = yaml.load(data_file, Loader=yaml.FullLoader)
                return trainer_config
        except IOError:
            raise EFLEXAgentEnvironmentException("""Parameter file could not be found here {}.
                                            Will use default Hyper parameters"""
                                                 .format(_trainer_config_path))
        except UnicodeDecodeError:
            raise EFLEXAgentEnvironmentException("There was an error decoding Trainer Config from this path : {}"
                                                 .format(_trainer_config_path))

    def step(self, action):
        """

        Parameters
        ----------
        action :

        Returns
        -------
        ob, reward, episode_over, info : tuple
            ob (object) :
                an environment-specific object representing your observation of
                the environment.
            reward (float) :
                amount of reward achieved by the previous action. The scale
                varies between environments, but the goal is always to increase
                your total reward.
            episode_over (bool) :
                whether it's time to reset the environment again. Most (but not
                all) tasks are divided up into well-defined episodes, and done
                being True indicates the episode has terminated. (For example,
                perhaps the pole tipped too far, or you lost your last life.)
            info (dict) :
                 diagnostic information useful for debugging. It can sometimes
                 be useful for learning (for example, it might contain the raw
                 probabilities behind the environment's last state change).
                 However, official evaluations of your agent are not allowed to
                 use this for learning.
        """
        obs_n = []
        reward_n = []
        done_n = []
        info_n = {'n': []}
        current_power_n = []

        current_energy_price = self.tou_generator.step()
        max_load_pofile = self.load_profile.step()
        production = 0
        info_n['current_energy_price'] = current_energy_price
        info_n['max_load_pofile'] = max_load_pofile

        # set action for each agent
        for i, agent in enumerate(self.agents):
            last_agent_state = agent.current_state.value

            _ob, _state_reward, _eo, _info = agent.step(action[i])
            # record observation for each agent
            obs_n.append(_ob)
            done_n.append(_eo)
            current_power_n.append(agent.current_power)
            info_n['n'].append(_info)

            # production machine are encouraged to produce
            _production_reward = 0.0
            if hasattr(agent, 'production_count'):
                if agent.current_state.value is EFLEXAgentState.Completed.value \
                        and last_agent_state is EFLEXAgentState.Execute.value:
                    _production_reward = 1.0
                    production = production + 1
                reward_n.append(0.5 * _state_reward + 0.5 * _production_reward)
                agent.current_reward = 0.5 * _state_reward + 0.5 * _production_reward

                if agent.production_count >= MAX_PRODUCTION_STEP:
                    self.current_winner.append(i)
            else:
                reward_n.append(_state_reward)

        # all agents get total reward in cooperative case
        reward = np.sum(reward_n)

        if self.shared_reward:
            reward_n = [reward] * self.n

        # done
        done = np.sum(np.array(done_n, dtype=np.bool)) > 0

        # Check if the total energy is smaller than the maximum allowed energy
        self.current_system_power = np.sum(np.array(current_power_n))
        info_n['current_system_power'] = self.current_system_power
        info_n['energy_cost_budget'] = self.energy_cost_budget
        if (self.current_system_power * current_energy_price) > self.energy_cost_budget:
            # set a maximum negative reward to all agents
            # reward_n = [-0.5] * self.n
            reward_n = [(r - 0.5) for r in reward_n]
            done = True

        info_n['production'] = production

        self.global_reward = np.mean(reward_n)
        return obs_n, reward_n, done, info_n

    def reset(self):
        obs_n = []
        for i, agent in enumerate(self.agents):
            _ob = agent.reset()
            obs_n.append(_ob)

        # reset the winner
        self.current_winner = []
        self.global_reward = 0.0
        self.current_system_power = 0.0

        # Reset the TOU Genrator and the load Profile
        self.tou_generator.reset()
        self.load_profile.reset()

        return obs_n

    def render(self, mode='human', close=False):
        tmp = '\t|\t'.join('{:<10} - State: {:<12} - Reward: {:.2f} - PC: {:.2f}'
                           .format(agent.name,
                                   agent.current_state.name,
                                   agent.current_reward,
                                   agent.production_count if hasattr(
                                       agent,
                                       'production_count') else 0.0)
                           for i, agent in enumerate(self.agents))
        print(
            'POWER: {:>6}%\t|\t WINNER: {:>6}\t|\t{}'.format(self.current_system_power, str(self.current_winner), tmp))

    def seed(self, seed=None):
        self.seed_value = seed
        if self.load_profile is not None:
            self.load_profile.seed(seed)

        if self.tou_generator is not None:
            self.tou_generator.seed(seed)

        for i, agent in enumerate(self.agents):
            agent.seed(seed)

    def close(self, seed=None):
        for i, agent in enumerate(self.agents):
            agent.close()

    def _is_episode_over(self):
        for i, agent in enumerate(self.agents):
            if agent._is_episode_over():
                return True
        ## TODO: Update the signal by considering the maximum load


class EFlexAgent:
    metadata = {'render.modes': ['human']}

    def __init__(self, agent_conf, name, max_allowed_power):
        # action space specify which transition can be activated
        self.action_space = spaces.Discrete(len(EFLEXAgentTransition))  # {0,1,...,n-1}

        # observation is a multi discrete specifying which state is activated
        # self.observation_space = spaces.MultiBinary(len(EFLEXAgentState))
        self.observation_space = spaces.Box(low=-10000.0, high=10000.0, shape=(len(EFLEXAgentState) + 2,),
                                            dtype=np.float32)


        # reward_range
        self.reward_range = (float(-1.0), float(1.0))

        # Simulation related variables.
        self.p_min = agent_conf['p_min']
        self.p_max = agent_conf['p_max']
        self.p_slope = agent_conf['p_slope']
        self.name = name
        self.current_state = None
        self.np_random = None
        self.current_reward = 0.0
        self.obs = None
        self.obs_pre = None
        self.max_allowed_power = max_allowed_power

        self.seed()
        self.reset()

        # Just need to initialize the relevant attributes
        self._configure()
        self.startStep = 0
        self.currentStep = 0

        # production data
        self.production_count = 0.0

    def _configure(self, display=None):
        self.display = display

    def step(self, action):
        """

        Parameters
        ----------
        action :

        Returns
        -------
        ob, state_reward, current_power, episode_over, info : tuple
            ob (object) :
                an environment-specific object representing your observation of
                the environment.
            state_reward (float) :
                amount of reward achieved by the previous action. The scale
                varies between environments, but the goal is always to increase
                your total reward.
            current_power (float) :
                amount of energy power consumed or produced.
            episode_over (bool) :
                whether it's time to reset the environment again. Most (but not
                all) tasks are divided up into well-defined episodes, and done
                being True indicates the episode has terminated. (For example,
                perhaps the pole tipped too far, or you lost your last life.)
            info (dict) :
                 diagnostic information useful for debugging. It can sometimes
                 be useful for learning (for example, it might contain the raw
                 probabilities behind the environment's last state change).
                 However, official evaluations of your agent are not allowed to
                 use this for learning.
        """
        last_state = self.current_state
        act_enum = EFLEXAgentTransition(action)
        self._take_action(act_enum)
        next_state = self.current_state
        reward = self._get_reward()
        ob = self._get_obs()

        episode_over = self._get_done()
        self.currentStep = self.currentStep + 1
        return ob, reward, episode_over, {'info': '{} => {} => {}'.format(last_state, EFLEXAgentTransition(action)
                                                                          , next_state)}

    def reset(self):
        # self.current_state = EFLEXAgentState(randint(0, len(EFLEXAgentState)-1))
        # while self.current_state is EFLEXAgentState.LoadChange:
        #     self.current_state = EFLEXAgentState(randint(0, len(EFLEXAgentState) -1))
        self.current_state = EFLEXAgentState.Stopped
        self.current_reward = 0.0
        self.currentStep = 0
        self.startStep = self.currentStep
        # production data
        self.production_count = 0.0
        return self._get_obs()

    def seed(self, seed=None):
        self.np_random, seed = seeding.np_random(seed)
        return [seed]

    def close(self, seed=None):
        pass

    def _take_action(self, action):
        # Aborted
        if self.current_state is EFLEXAgentState.Aborted:
            self.startStep = self.currentStep
            if action is EFLEXAgentTransition.Clear:
                self.current_state = EFLEXAgentState.Stopped
                self.current_reward = 1.0
            else:
                self.current_state = EFLEXAgentState.Aborted
                self.current_reward = 0.0
        # Stopped
        elif self.current_state is EFLEXAgentState.Stopped:
            self.startStep = self.currentStep
            if action is EFLEXAgentTransition.Abort:
                self.current_state = EFLEXAgentState.Aborted
                self.current_reward = -0.1
            elif action is EFLEXAgentTransition.Reset:
                self.current_state = EFLEXAgentState.Idle
                self.current_reward = 0.1
            else:
                self.current_state = EFLEXAgentState.Stopped
                self.current_reward = 0.0
        # Idle
        elif self.current_state is EFLEXAgentState.Idle:
            if action is EFLEXAgentTransition.Abort:
                self.current_state = EFLEXAgentState.Aborted
                self.current_reward = -0.1
            elif action is EFLEXAgentTransition.Start:
                self.startStep = self.currentStep
                self.current_state = EFLEXAgentState.Execute
                self.current_reward = 1.0
            elif action is EFLEXAgentTransition.PowerOff:
                self.current_state = EFLEXAgentState.PowerOff
                self.current_reward = 0.0
            elif action is EFLEXAgentTransition.Standby:
                self.current_state = EFLEXAgentState.StandBy
                self.current_reward = 0.0
            elif action is EFLEXAgentTransition.Stop:
                self.current_state = EFLEXAgentState.Stopped
                self.current_reward = 0.0
            elif action is EFLEXAgentTransition.ChangeLoad:
                self.current_state = EFLEXAgentState.Idle
                self.current_reward = 0.1
            else:
                self.current_state = EFLEXAgentState.Idle
                self.current_reward = 0.0
        # PowerOff
        elif self.current_state is EFLEXAgentState.PowerOff:
            self.startStep = self.currentStep
            if action is EFLEXAgentTransition.Abort:
                self.current_state = EFLEXAgentState.Aborted
                self.current_reward = -0.1
            elif action is EFLEXAgentTransition.PowerOn:
                self.current_state = EFLEXAgentState.StartedUp
                self.current_reward = 0.0
            elif action is EFLEXAgentTransition.Stop:
                self.current_state = EFLEXAgentState.Stopped
                self.current_reward = 0.0
            else:
                self.current_state = EFLEXAgentState.PowerOff
                self.current_reward = 0.0
        # StandBy
        elif self.current_state is EFLEXAgentState.StandBy:
            self.startStep = self.currentStep
            if action is EFLEXAgentTransition.Abort:
                self.current_state = EFLEXAgentState.Aborted
                self.current_reward = -0.1
            elif action is EFLEXAgentTransition.PowerOn:
                self.current_state = EFLEXAgentState.StartedUp
                self.current_reward = 0.1
            elif action is EFLEXAgentTransition.Stop:
                self.current_state = EFLEXAgentState.Stopped
                self.current_reward = 0.0
            else:
                self.current_state = EFLEXAgentState.StandBy
                self.current_reward = 0.0
        # StartedUp
        elif self.current_state is EFLEXAgentState.StartedUp:
            if action is EFLEXAgentTransition.Abort:
                self.current_state = EFLEXAgentState.Aborted
                self.current_reward = -0.1
            elif action is EFLEXAgentTransition.Reset:
                self.current_state = EFLEXAgentState.Idle
                self.current_reward = 0.3
            elif action is EFLEXAgentTransition.Stop:
                self.current_state = EFLEXAgentState.Stopped
                self.current_reward = 0.0
            else:
                self.current_state = EFLEXAgentState.StartedUp
                self.current_reward = 0.0
        # Execute
        elif self.current_state is EFLEXAgentState.Execute:
            if action is EFLEXAgentTransition.Abort:
                self.current_state = EFLEXAgentState.Aborted
                self.current_reward = -0.1
            elif action is EFLEXAgentTransition.SC:
                self.current_state = EFLEXAgentState.Completed
                self.current_reward = 1.0
                self.production_count = self.production_count + 1
            elif action is EFLEXAgentTransition.Hold:
                self.current_state = EFLEXAgentState.Held
                self.current_reward = 0.0
            elif action is EFLEXAgentTransition.Suspend:
                self.current_state = EFLEXAgentState.Suspended
                self.current_reward = 0.0
            elif action is EFLEXAgentTransition.Stop:
                self.current_state = EFLEXAgentState.Stopped
                self.current_reward = 0.0
            elif action is EFLEXAgentTransition.ChangeLoad:
                self.current_state = EFLEXAgentState.Execute
                self.current_reward = 0.0
            else:
                self.current_state = EFLEXAgentState.Execute
                self.current_reward = 0.0
        # Complete
        elif self.current_state is EFLEXAgentState.Completed:
            if action is EFLEXAgentTransition.Abort:
                self.current_state = EFLEXAgentState.Aborted
                self.current_reward = -0.1
            elif action is EFLEXAgentTransition.SC:
                self.current_state = EFLEXAgentState.Idle
                self.current_reward = 1.0
            elif action is EFLEXAgentTransition.Stop:
                self.current_state = EFLEXAgentState.Stopped
                self.current_reward = 0.0
            else:
                self.current_state = EFLEXAgentState.Completed
                self.current_reward = 0.0
        # Held
        elif self.current_state is EFLEXAgentState.Held:
            if action is EFLEXAgentTransition.Abort:
                self.current_state = EFLEXAgentState.Aborted
                self.current_reward = -0.1
            elif action is EFLEXAgentTransition.UnHold:
                self.current_state = EFLEXAgentState.Execute
                self.current_reward = 0.1
            elif action is EFLEXAgentTransition.Suspend:
                self.current_state = EFLEXAgentState.Suspended
                self.current_reward = 0.0
            elif action is EFLEXAgentTransition.Stop:
                self.current_state = EFLEXAgentState.Stopped
                self.current_reward = 0.0
            elif action is EFLEXAgentTransition.ChangeLoad:
                self.current_state = EFLEXAgentState.Held
                self.current_reward = 0.0
            else:
                self.current_state = EFLEXAgentState.Held
                self.current_reward = 0.0
        # Suspended
        elif self.current_state is EFLEXAgentState.Suspended:
            if action is EFLEXAgentTransition.Abort:
                self.current_state = EFLEXAgentState.Aborted
                self.current_reward = -0.1
            elif action is EFLEXAgentTransition.Unsuspend:
                self.current_state = EFLEXAgentState.Execute
                self.current_reward = 0.1
            elif action is EFLEXAgentTransition.Hold:
                self.current_state = EFLEXAgentState.Held
                self.current_reward = 0.0
            elif action is EFLEXAgentTransition.Stop:
                self.current_state = EFLEXAgentState.Stopped
                self.current_reward = 0.0
            elif action is EFLEXAgentTransition.ChangeLoad:
                self.current_state = EFLEXAgentState.Suspended
                self.current_reward = 0.0
            else:
                self.current_state = EFLEXAgentState.Suspended
                self.current_reward = 0.0

    def _get_obs(self):
        obs = np.zeros(self.observation_space.shape)
        obs[self.current_state.value] = 1.0
        obs[self.observation_space.shape[0] - 1] = self.current_power / self.max_allowed_power
        # obs[self.observation_space.n - 1] = self.production_count / MAX_PRODUCTION_STEP

        return obs

    def _get_done(self):
        return self.current_state is EFLEXAgentState.Aborted or self.production_count >= MAX_PRODUCTION_STEP

    def _get_reward(self):
        return self.current_reward

    @property
    def current_power(self):
        raise NotImplementedError("Please Implement this method")


class EFlexAgentPConstant(EFlexAgent):
    metadata = {'render.modes': ['human']}

    @property
    def current_power(self):
        if self.current_state is EFLEXAgentState.Aborted or self.current_state is EFLEXAgentState.Stopped:
            return 0.0
        elif self.current_state is EFLEXAgentState.Execute or self.current_state is EFLEXAgentState.Completed:
            return self.p_max
        else:
            return self.p_min


class EFlexAgentPLinear(EFlexAgent):
    metadata = {'render.modes': ['human']}

    @property
    def current_power(self):
        if self.current_state is EFLEXAgentState.Aborted or self.current_state is EFLEXAgentState.Stopped:
            return 0.0
        elif self.current_state is EFLEXAgentState.Execute or self.current_state is EFLEXAgentState.Completed:
            delta = self.currentStep - self.startStep
            c_power = self.p_min + delta * self.p_slope
            if c_power > self.p_max:
                return self.p_max
            else:
                return c_power
        else:
            return self.p_min


class EFlexAgentPLogistic(EFlexAgent):
    metadata = {'render.modes': ['human']}

    @staticmethod
    def sigmoid(x, k, l):
        return l / (1 + math.exp(- l * x))

    @property
    def current_power(self):

        if self.current_state is EFLEXAgentState.Aborted or self.current_state is EFLEXAgentState.Stopped:
            return 0.0
        elif self.current_state is EFLEXAgentState.Execute or self.current_state is EFLEXAgentState.Completed:
            delta = self.currentStep - self.startStep
            c_power = self.p_min + self.sigmoid(delta, self.p_slope, self.p_max)
            if c_power > self.p_max:
                return self.p_max
            else:
                return c_power
        else:
            return self.p_min


class EFLEXEnergyStorageAgentState(Enum):
    Aborted = 1
    Stopped = 0
    Charging = 2
    Discharging = 3


class EFLEXEnergyStorageAgentTransition(Enum):
    SC = 0
    Abort = 1
    Clear = 2
    Charge = 3
    Stop = 4
    Discharge = 5


class EFlexEnergyStorageAgent:
    metadata = {'render.modes': ['human']}

    def __init__(self, agent_conf, name, max_allowed_power):
        # action space specify which transition can be activated
        self.action_space = spaces.Discrete(len(EFLEXEnergyStorageAgentTransition))  # {0,1,...,n-1}

        # observation is a multi discrete specifying which state is activated
        # self.observation_space = spaces.MultiBinary(len(EFLEXEnergyStorageAgentState) + 1)
        # self.observation_space = spaces.MultiBinary(len(EFLEXEnergyStorageAgentState))
        self.observation_space = spaces.Box(low=-10000.0, high=10000.0, shape=(len(EFLEXEnergyStorageAgentState) + 2,),
                                            dtype=np.float32)

        # reward_range
        self.reward_range = (float(-1.0), float(1.0))

        # Simulation related variables.
        self.p_min = agent_conf['p_min']
        self.p_max = agent_conf['p_max']
        self.p_slope = agent_conf['p_slope']
        self.name = name
        self.current_state = None
        self.np_random = None
        self.current_reward = 0.0
        self.obs = None
        self.obs_pre = None
        self.max_allowed_power = max_allowed_power

        self.seed()
        self.reset()

        # Just need to initialize the relevant attributes
        self._configure()
        self.startStep = 0
        self.currentStep = 0
        self.charging_level = 0

    def _configure(self, display=None):
        self.display = display

    def step(self, action):
        """

        Parameters
        ----------
        action :

        Returns
        -------
        ob, state_reward, current_power, episode_over, info : tuple
            ob (object) :
                an environment-specific object representing your observation of
                the environment.
            state_reward (float) :
                amount of reward achieved by the previous action. The scale
                varies between environments, but the goal is always to increase
                your total reward.
            current_power (float) :
                amount of energy power consumed or produced.
            episode_over (bool) :
                whether it's time to reset the environment again. Most (but not
                all) tasks are divided up into well-defined episodes, and done
                being True indicates the episode has terminated. (For example,
                perhaps the pole tipped too far, or you lost your last life.)
            info (dict) :
                 diagnostic information useful for debugging. It can sometimes
                 be useful for learning (for example, it might contain the raw
                 probabilities behind the environment's last state change).
                 However, official evaluations of your agent are not allowed to
                 use this for learning.
        """
        last_state = self.current_state
        act_enum = EFLEXEnergyStorageAgentTransition(action)
        self._take_action(act_enum)
        next_state = self.current_state
        reward = self._get_reward()
        ob = self._get_obs()

        episode_over = self._get_done()
        self.currentStep = self.currentStep + 1
        return ob, reward, episode_over, {'info': '{} => {} => {}'.format(last_state,
                                                                          EFLEXEnergyStorageAgentTransition(action)
                                                                          , next_state)}

    def reset(self):
        # self.current_state = EFLEXAgentState(randint(0, len(EFLEXAgentState)-1))
        # while self.current_state is EFLEXAgentState.LoadChange:
        #     self.current_state = EFLEXAgentState(randint(0, len(EFLEXAgentState) -1))
        self.current_state = EFLEXEnergyStorageAgentState.Stopped
        self.current_reward = 0.0
        self.currentStep = 0
        self.startStep = self.currentStep
        return self._get_obs()

    def seed(self, seed=None):
        self.np_random, seed = seeding.np_random(seed)
        return [seed]

    def close(self, seed=None):
        pass

    def _take_action(self, action):
        # Aborted
        if self.current_state is EFLEXEnergyStorageAgentState.Aborted:
            self.startStep = self.currentStep
            if action is EFLEXEnergyStorageAgentTransition.Clear:
                self.current_state = EFLEXEnergyStorageAgentState.Stopped
                self.current_reward = 1.0
            else:
                self.current_state = EFLEXEnergyStorageAgentState.Aborted
                self.current_reward = 0.0
        # Stopped
        elif self.current_state is EFLEXEnergyStorageAgentState.Stopped:
            self.startStep = self.currentStep
            if action is EFLEXEnergyStorageAgentTransition.Abort:
                self.current_state = EFLEXEnergyStorageAgentState.Aborted
                self.current_reward = -0.1
            elif action is EFLEXEnergyStorageAgentTransition.Charge:
                self.current_state = EFLEXEnergyStorageAgentState.Charging
                self.current_reward = 0.1
            elif action is EFLEXEnergyStorageAgentTransition.Discharge:
                self.current_state = EFLEXEnergyStorageAgentState.Discharging
                self.current_reward = 0.1
            else:
                self.current_state = EFLEXEnergyStorageAgentState.Stopped
                self.current_reward = 0.0
        # Charging
        elif self.current_state is EFLEXEnergyStorageAgentState.Charging:
            if action is EFLEXEnergyStorageAgentTransition.Abort:
                self.current_state = EFLEXEnergyStorageAgentState.Aborted
                self.current_reward = -0.1
            elif action is EFLEXEnergyStorageAgentTransition.Stop:
                self.current_state = EFLEXEnergyStorageAgentState.Stopped
                self.current_reward = 0.0
            elif action is EFLEXEnergyStorageAgentTransition.Discharge:
                self.current_state = EFLEXEnergyStorageAgentState.Discharging
                val = 0.5 * (1 - ((self.p_max - self.charging_level) ** 2 / (self.p_max ** 2)))
                self.current_reward = val
            else:
                self.current_state = EFLEXEnergyStorageAgentState.Charging
                val = 0.5 * (1 - ((self.p_max - self.charging_level) ** 2 / (self.p_max ** 2)))
                self.current_reward = val

            self.charging_level = self.charging_level + self.p_slope
            if self.charging_level > self.p_max:
                self.charging_level = self.p_max
        # Discharging
        elif self.current_state is EFLEXEnergyStorageAgentState.Discharging:
            if action is EFLEXEnergyStorageAgentTransition.Abort:
                self.current_state = EFLEXEnergyStorageAgentState.Aborted
                self.current_reward = -0.1
            elif action is EFLEXEnergyStorageAgentTransition.Stop:
                self.current_state = EFLEXEnergyStorageAgentState.Stopped
                self.current_reward = 0.0
            elif action is EFLEXEnergyStorageAgentTransition.Charge:
                self.current_state = EFLEXEnergyStorageAgentState.Charging
                val = 0.5 * (1 - ((self.p_max - self.charging_level) ** 2 / (self.p_max ** 2)))
                self.current_reward = val
            else:
                self.current_state = EFLEXEnergyStorageAgentState.Discharging
                val = 0.5 * (1 - ((self.p_max - self.charging_level) ** 2 / (self.p_max ** 2)))
                self.current_reward = val

            self.charging_level = self.charging_level - self.p_slope
            if self.charging_level < self.p_min:
                self.charging_level = self.p_min

    def _get_obs(self):
        obs = np.zeros(self.observation_space.shape)
        obs[self.current_state.value] = 1.0
        obs[self.observation_space.shape[0] - 1] = self.current_power / self.max_allowed_power

        return obs

    def _get_done(self):
        return self.current_state is EFLEXEnergyStorageAgentState.Aborted

    def _get_reward(self):
        return self.current_reward

    @property
    def current_power(self):
        if self.current_state is EFLEXEnergyStorageAgentState.Aborted or \
                self.current_state is EFLEXEnergyStorageAgentState.Stopped:
            return 0.0
        elif self.current_state is EFLEXEnergyStorageAgentState.Charging:
            if self.charging_level < self.p_max:
                return (self.p_max - self.p_min) / 2
            else:
                return 0.0
        elif self.current_state is EFLEXEnergyStorageAgentState.Discharging:
            if self.charging_level > self.p_min:
                return - (self.p_max - self.p_min) / 2
            else:
                return 0.0
        else:
            return 0


class EFLEXEnergyGeneratorAgentState(Enum):
    Aborted = 1
    Stopped = 0
    Generating = 2


class EFLEXEnergyGeneratorAgentTransition(Enum):
    SC = 0
    Abort = 1
    Clear = 2
    Generate = 3
    Stop = 4


class EFLEXEnergyGeneratorAgent:
    metadata = {'render.modes': ['human']}

    def __init__(self, agent_conf, name, max_allowed_power):
        # action space specify which transition can be activated
        self.action_space = spaces.Discrete(len(EFLEXEnergyGeneratorAgentTransition))  # {0,1,...,n-1}

        # observation is a multi discrete specifying which state is activated
        # self.observation_space = spaces.MultiBinary(len(EFLEXEnergyGeneratorAgentState) + 1)
        # self.observation_space = spaces.MultiBinary(len(EFLEXEnergyGeneratorAgentState))
        self.observation_space = spaces.Box(low=-1.0, high=2.0, shape=(len(EFLEXEnergyGeneratorAgentState) + 2,),
                                            dtype=np.float32)

        # reward_range
        self.reward_range = (float(-1.0), float(1.0))

        # Simulation related variables.
        self.p_min = agent_conf['p_min']
        self.p_max = agent_conf['p_max']
        self.p_slope = agent_conf['p_slope']
        self.name = name
        self.current_state = None
        self.np_random = None
        self.current_reward = 0.0
        self.obs = None
        self.obs_pre = None
        self.max_allowed_power = max_allowed_power

        self.seed()
        self.reset()

        # Just need to initialize the relevant attributes
        self._configure()
        self.startStep = 0
        self.currentStep = 0
        self.last_power = 0

    def _configure(self, display=None):
        self.display = display

    def step(self, action):
        """

        Parameters
        ----------
        action :

        Returns
        -------
        ob, state_reward, current_power, episode_over, info : tuple
            ob (object) :
                an environment-specific object representing your observation of
                the environment.
            state_reward (float) :
                amount of reward achieved by the previous action. The scale
                varies between environments, but the goal is always to increase
                your total reward.
            current_power (float) :
                amount of energy power consumed or produced.
            episode_over (bool) :
                whether it's time to reset the environment again. Most (but not
                all) tasks are divided up into well-defined episodes, and done
                being True indicates the episode has terminated. (For example,
                perhaps the pole tipped too far, or you lost your last life.)
            info (dict) :
                 diagnostic information useful for debugging. It can sometimes
                 be useful for learning (for example, it might contain the raw
                 probabilities behind the environment's last state change).
                 However, official evaluations of your agent are not allowed to
                 use this for learning.
        """
        last_state = self.current_state
        act_enum = EFLEXEnergyGeneratorAgentTransition(action)
        self._take_action(act_enum)
        next_state = self.current_state
        reward = self._get_reward()
        ob = self._get_obs()

        episode_over = self._get_done()
        self.currentStep = self.currentStep + 1
        self.last_power = abs(self.current_power)
        return ob, reward, episode_over, {'info': '{} => {} => {}'.format(last_state,
                                                                          EFLEXEnergyGeneratorAgentTransition(action)
                                                                          , next_state)}

    def reset(self):
        # self.current_state = EFLEXAgentState(randint(0, len(EFLEXAgentState)-1))
        # while self.current_state is EFLEXAgentState.LoadChange:
        #     self.current_state = EFLEXAgentState(randint(0, len(EFLEXAgentState) -1))
        self.current_state = EFLEXEnergyGeneratorAgentState.Stopped
        self.current_reward = 0.0
        self.currentStep = 0
        self.startStep = self.currentStep
        return self._get_obs()

    def seed(self, seed=None):
        self.np_random, seed = seeding.np_random(seed)
        return [seed]

    def close(self, seed=None):
        pass

    def _take_action(self, action):
        # Aborted
        if self.current_state is EFLEXEnergyGeneratorAgentState.Aborted:
            self.startStep = self.currentStep
            if action is EFLEXEnergyGeneratorAgentTransition.Clear:
                self.current_state = EFLEXEnergyGeneratorAgentState.Stopped
                self.current_reward = 1.0
            else:
                self.current_state = EFLEXEnergyGeneratorAgentState.Aborted
                self.current_reward = 0.0
        # Stopped
        elif self.current_state is EFLEXEnergyGeneratorAgentState.Stopped:
            self.startStep = self.currentStep
            if action is EFLEXEnergyGeneratorAgentTransition.Abort:
                self.current_state = EFLEXEnergyGeneratorAgentState.Aborted
                self.current_reward = -0.1
            elif action is EFLEXEnergyGeneratorAgentTransition.Generate:
                self.current_state = EFLEXEnergyGeneratorAgentState.Generating
                self.current_reward = 0.1
            else:
                self.current_state = EFLEXEnergyGeneratorAgentState.Stopped
                self.current_reward = 0.0
        # Generating
        elif self.current_state is EFLEXEnergyGeneratorAgentState.Generating:
            if action is EFLEXEnergyGeneratorAgentTransition.Abort:
                self.current_state = EFLEXEnergyGeneratorAgentState.Aborted
                self.current_reward = -0.1
            elif action is EFLEXEnergyGeneratorAgentTransition.Stop:
                self.current_state = EFLEXEnergyGeneratorAgentState.Stopped
                self.current_reward = 0.0
            else:
                self.current_state = EFLEXEnergyGeneratorAgentState.Generating
                self.current_reward = 0.2 * abs(self.current_power / self.p_max)

    def _get_obs(self):
        obs = np.zeros(self.observation_space.shape)
        obs[self.current_state.value] = 1.0
        obs[self.observation_space.shape[0] - 1] = self.current_power / self.max_allowed_power
        return obs

    def _get_done(self):
        return self.current_state is EFLEXEnergyGeneratorAgentState.Aborted

    def _get_reward(self):
        return self.current_reward

    @property
    def current_power(self):
        if self.current_state is EFLEXEnergyGeneratorAgentState.Aborted or \
                self.current_state is EFLEXEnergyGeneratorAgentState.Stopped:
            return 0.0
        elif self.current_state is EFLEXEnergyGeneratorAgentState.Generating:
            c_power = self.last_power + self.p_slope
            if c_power > self.p_max:
                return - self.p_max
            else:
                return - c_power
        else:
            return 0


class EFLEXEnergyMainGridAgentState(Enum):
    Aborted = 0
    Stopped = 1
    Buying = 2
    Selling = 4


class EFLEXEnergyMainGridAgentTransition(Enum):
    SC = 0
    Abort = 1
    Clear = 2
    Stop = 3
    Buy = 4
    Sell = 5


class EFLEXEnergyMainGridAgent:
    metadata = {'render.modes': ['human']}

    def __init__(self, agent_conf, name, max_allowed_power):
        # action space specify which transition can be activated
        self.action_space = spaces.Discrete(len(EFLEXEnergyMainGridAgentTransition))  # {0,1,...,n-1}

        # observation is a multi discrete specifying which state is activated
        # self.observation_space = spaces.MultiBinary(len(EFLEXEnergyMainGridAgentState))
        # self.observation_space = spaces.MultiBinary(len(EFLEXEnergyMainGridAgentState) + 1)
        self.observation_space = spaces.Box(low=-10000.0, high=10000.0, shape=(len(EFLEXEnergyMainGridAgentState) + 2,),
                                            dtype=np.float32)

        # reward_range
        self.reward_range = (float(-1.0), float(1.0))

        # Simulation related variables.
        self.p_min = agent_conf['p_min']
        self.p_max = agent_conf['p_max']
        self.p_slope = agent_conf['p_slope']
        self.name = name
        self.current_state = None
        self.np_random = None
        self.current_reward = 0.0
        self.obs = None
        self.obs_pre = None
        self.max_allowed_power = max_allowed_power

        self.seed()
        self.reset()

        # Just need to initialize the relevant attributes
        self._configure()
        self.startStep = 0
        self.currentStep = 0
        self.last_power = 0

    def _configure(self, display=None):
        self.display = display

    def step(self, action):
        """

        Parameters
        ----------
        action : action to be performed

        Returns
        -------
        ob, state_reward, current_power, episode_over, info : tuple
            ob (object) :
                an environment-specific object representing your observation of
                the environment.
            state_reward (float) :
                amount of reward achieved by the previous action. The scale
                varies between environments, but the goal is always to increase
                your total reward.
            current_power (float) :
                amount of energy power consumed or produced.
            episode_over (bool) :
                whether it's time to reset the environment again. Most (but not
                all) tasks are divided up into well-defined episodes, and done
                being True indicates the episode has terminated. (For example,
                perhaps the pole tipped too far, or you lost your last life.)
            info (dict) :
                 diagnostic information useful for debugging. It can sometimes
                 be useful for learning (for example, it might contain the raw
                 probabilities behind the environment's last state change).
                 However, official evaluations of your agent are not allowed to
                 use this for learning.
        """
        last_state = self.current_state
        act_enum = EFLEXEnergyMainGridAgentTransition(action)
        self._take_action(act_enum)
        next_state = self.current_state
        reward = self._get_reward()
        ob = self._get_obs()

        episode_over = self._get_done()
        self.currentStep = self.currentStep + 1
        self.last_power = self.current_power
        return ob, reward, episode_over, {'info': '{} => {} => {}'.format(last_state,
                                                                          EFLEXEnergyMainGridAgentTransition(action)
                                                                          , next_state)}

    def reset(self):
        self.current_state = EFLEXEnergyMainGridAgentState.Stopped
        self.current_reward = 0.0
        self.currentStep = 0
        self.startStep = self.currentStep
        return self._get_obs()

    def seed(self, seed=None):
        self.np_random, seed = seeding.np_random(seed)
        return [seed]

    def close(self, seed=None):
        pass

    def _take_action(self, action):
        # Aborted
        if self.current_state is EFLEXEnergyMainGridAgentState.Aborted:
            self.startStep = self.currentStep
            if action is EFLEXEnergyMainGridAgentTransition.Clear:
                # self.current_state = EFLEXEnergyMainGridAgentState.Stopped
                # self.current_reward = 1.0
                pass
            else:
                self.current_state = EFLEXEnergyMainGridAgentState.Aborted
                self.current_reward = 0.0
        # Stopped
        elif self.current_state is EFLEXEnergyMainGridAgentState.Stopped:
            self.startStep = self.currentStep
            if action is EFLEXEnergyMainGridAgentTransition.Abort:
                self.current_state = EFLEXEnergyMainGridAgentState.Aborted
                self.current_reward = -0.1
            elif action is EFLEXEnergyMainGridAgentTransition.Buy:
                self.current_state = EFLEXEnergyMainGridAgentState.Buying
                self.current_reward = 0.01
            elif action is EFLEXEnergyMainGridAgentTransition.Sell:
                self.current_state = EFLEXEnergyMainGridAgentState.Selling
                self.current_reward = 0.01
            else:
                self.current_state = EFLEXEnergyMainGridAgentState.Stopped
                self.current_reward = 0.0
        # Buying
        elif self.current_state is EFLEXEnergyMainGridAgentState.Buying:
            if action is EFLEXEnergyMainGridAgentTransition.Abort:
                self.current_state = EFLEXEnergyMainGridAgentState.Aborted
                self.current_reward = -0.1
            elif action is EFLEXEnergyMainGridAgentTransition.Stop:
                self.current_state = EFLEXEnergyMainGridAgentState.Stopped
                self.current_reward = -0.01
            elif action is EFLEXEnergyMainGridAgentTransition.Sell:
                self.current_state = EFLEXEnergyMainGridAgentState.Selling
                self.current_reward = 0.0
            else:
                self.current_state = self.current_state = EFLEXEnergyMainGridAgentState.Buying
                self.current_reward = -0.01
        # Selling
        elif self.current_state is EFLEXEnergyMainGridAgentState.Selling:
            if action is EFLEXEnergyMainGridAgentTransition.Abort:
                self.current_state = EFLEXEnergyMainGridAgentState.Aborted
                self.current_reward = -0.1
            elif action is EFLEXEnergyMainGridAgentTransition.Stop:
                self.current_state = EFLEXEnergyMainGridAgentState.Stopped
                self.current_reward = -0.01
            elif action is EFLEXEnergyMainGridAgentTransition.Buy:
                self.current_state = EFLEXEnergyMainGridAgentState.Buying
                self.current_reward = 0.0
            else:
                self.current_state = self.current_state = EFLEXEnergyMainGridAgentState.Selling
                self.current_reward = 0.01

    def _get_obs(self):
        obs = np.zeros(self.observation_space.shape)
        obs[self.current_state.value] = 1.0
        obs[self.observation_space.shape[0] - 1] = self.current_power / self.max_allowed_power

        return obs

    def _get_done(self):
        return self.current_state is EFLEXEnergyMainGridAgentState.Aborted

    def _get_reward(self):
        return self.current_reward

    @property
    def current_power(self):
        if self.current_state is EFLEXEnergyMainGridAgentState.Aborted or \
                self.current_state is EFLEXEnergyMainGridAgentState.Stopped:
            return 0.0
        elif self.current_state is EFLEXEnergyMainGridAgentState.Buying:
            return - self.p_max
        elif self.current_state is EFLEXEnergyMainGridAgentState.Selling:
            return self.p_max
        else:
            return 0
