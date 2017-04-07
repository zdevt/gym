import io
import os

import matplotlib.pyplot as plt
import numpy as np
from flask import Flask
from scipy import signal

from gym import monitoring
from gym.benchmarks import registry

app = Flask(__name__)



BENCHMARK_DATA_PATH = '/tmp/AtariExploration40M/'
BENCHMARK_ID = os.path.dirname(BENCHMARK_DATA_PATH)


class Evaluation(object):
    def __init__(self, results):
        self.env_id = results['env_info']['env_id']

        self.episode_rewards = results['episode_rewards']
        self.episode_lengths = results['episode_lengths']
        self.episode_types = results['episode_types']
        self.timestamps = results['timestamps']
        self.initial_reset_timestamps = results['initial_reset_timestamps']
        self.data_sources = results['data_sources']

    @classmethod
    def from_training_dir(cls, training_dir):
        results = monitoring.load_results(training_dir)
        return Evaluation(results)


class BenchmarkRun(object):
    def __init__(self, evaluations):
        self.evaluations = evaluations


def smooth_reward_curve(rewards, lengths, max_timestep, resolution=1e3, polyorder=3):
    # Don't use a higher resolution than the original data, use a window about
    # 1/10th the resolution
    resolution = min(len(rewards), resolution)
    window = int(resolution / 10)
    window = window + 1 if (window % 2 == 0) else window  # window must be odd

    if polyorder >= window:
        return lengths, rewards

    # Linear interpolation, followed by Savitzky-Golay filter
    x = np.cumsum(np.array(lengths, 'float'))
    y = np.array(rewards, 'float')

    x_spaced = np.linspace(0, max_timestep, resolution)
    y_interpolated = np.interp(x_spaced, x, y)
    y_smoothed = signal.savgol_filter(y_interpolated, window, polyorder=polyorder)

    return x_spaced.tolist(), y_smoothed.tolist()


class Task(object):
    def __init__(self, env_id, evaluations):
        self.env_id = env_id
        self.evaluations = evaluations

    def to_svg(self):
        plt.figure()
        plt.rcParams['figure.figsize'] = (15, 2)
        for trial in self.evaluations:
            xs, ys = smooth_reward_curve(
                trial.episode_rewards, trial.episode_lengths, 1e6)
            plt.plot(xs, ys)

        plt.xlabel('Time')
        plt.ylabel('Rewards')
        plt.tight_layout()
        img_bytes = io.StringIO()
        plt.savefig(img_bytes, format='svg')
        return img_bytes.getvalue()


def area_under_curve(episode_lengths, episode_rewards):
    """Compute the total area of rewards under the curve"""
    # TODO: Replace with slightly more accurate trapezoid method
    return np.sum(l * r for l, r in zip(episode_lengths, episode_rewards))


def mean_area_under_curve(episode_lengths, episode_rewards):
    """Compute the average area of rewards under the curve per unit of time"""
    return area_under_curve(episode_lengths, episode_rewards) / max(1e-4, np.sum(episode_lengths))


class BenchmarkScoreCache(object):
    def __init__(self, benchmark_id, min_reward_by_env, max_reward_by_env):
        self.min_reward_by_env = min_reward_by_env
        self.max_reward_by_env = max_reward_by_env

        self.id = benchmark_id


def score_evaluation(evaluation):
    benchmark = registry.benchmark_spec(BENCHMARK_ID)

    score_results = benchmark.score_evaluation(
        evaluation.env_id,
        data_sources=evaluation.data_sources,
        initial_reset_timestamps=evaluation.initial_reset_timestamps,
        episode_lengths=evaluation.episode_lengths,
        episode_rewards=evaluation.episode_rewards,
        episode_types=evaluation.episode_types,
        timestamps=evaluation.timestamps)

    # TODO: Why does the scorer output vectorized here?
    return mean_area_under_curve(
        score_results['lengths'][0],
        score_results['rewards'][0],
    )


@app.route('/')
def index():
    run_paths = os.listdir('/tmp/{}'.format(BENCHMARK_ID))

    for run_path in run_paths:
        tasks_from_bmrun_path(run_path)
    # Compute best and worst performance on each task

    # Compute rank for each of them

    # Show them in a list

    return "pending"


@app.route('/compare/<run_name>/<other_run_name>/')
def compare(run_name, other_run_name):
    pass


@app.route('/benchmark_run/<run_name>')
def view_tasks(run_name):
    tasks = tasks_from_bmrun_path(os.path.join(BENCHMARK_DATA_PATH, run_name))

    rows = ''.join(
        '<tr><td>{}</td><td>{}</td></tr>'.format(env_id, task.to_svg())
            for env_id, task in sorted(tasks.items())
    )
    return '<table>{}</tbody>'.format(rows)


def tasks_from_bmrun_path(path):
    """
    Returns a map of env_ids to tasks included in the run at the path
    """
    env_id_to_task = {}
    for root, _, fnames in os.walk(path):
        for fname in fnames:
            if not fname.endswith('manifest.json'):
                continue

            # Found a training dir
            training_dir = os.path.dirname(fname)
            print(training_dir)
            evaluation = Evaluation.from_training_dir(training_dir)

            env_id = evaluation.env_id

            if env_id not in env_id_to_task:
                env_id_to_task[env_id] = Task(env_id, [])
            task = env_id_to_task[env_id]

            print(evaluation.score())
            task.evaluations.append(evaluation)

    return env_id_to_task


if __name__ == '__main__':
    app.run(debug=True, port=5000)