from __future__ import print_function

import os
import string
from contextlib import contextmanager

import mock
import pytest
from click import UsageError
from click.testing import CliRunner

from dagster import (
    DagsterInvariantViolationError,
    PartitionSetDefinition,
    RepositoryDefinition,
    ScheduleDefinition,
    check,
    lambda_solid,
    pipeline,
    seven,
    solid,
)
from dagster.check import CheckError
from dagster.cli.pipeline import (
    execute_backfill_command,
    execute_execute_command,
    execute_list_command,
    execute_print_command,
    execute_scaffold_command,
    pipeline_backfill_command,
    pipeline_execute_command,
    pipeline_launch_command,
    pipeline_list_command,
    pipeline_print_command,
    pipeline_scaffold_command,
)
from dagster.cli.run import run_list_command, run_wipe_command
from dagster.cli.schedule import (
    schedule_list_command,
    schedule_restart_command,
    schedule_start_command,
    schedule_stop_command,
    schedule_up_command,
    schedule_wipe_command,
)
from dagster.config.field_utils import Shape
from dagster.core.instance import DagsterInstance, InstanceType
from dagster.core.launcher import RunLauncher
from dagster.core.launcher.sync_in_memory_run_launcher import SyncInMemoryRunLauncher
from dagster.core.storage.event_log import InMemoryEventLogStorage
from dagster.core.storage.local_compute_log_manager import NoOpComputeLogManager
from dagster.core.storage.root import LocalArtifactStorage
from dagster.core.storage.runs import InMemoryRunStorage
from dagster.core.storage.schedules import SqliteScheduleStorage
from dagster.serdes import ConfigurableClass
from dagster.utils import file_relative_path
from dagster.utils.test import FilesystemTestScheduler


def no_print(_):
    return None


@lambda_solid
def do_something():
    return 1


@lambda_solid
def do_input(x):
    return x


@pipeline(name='foo')
def foo_pipeline():
    do_input(do_something())


def define_foo_pipeline():
    return foo_pipeline


@pipeline(name='baz', description='Not much tbh')
def baz_pipeline():
    do_input()


def define_bar_repo():
    return RepositoryDefinition(
        name='bar',
        pipeline_dict={'foo': define_foo_pipeline, 'baz': lambda: baz_pipeline},
        schedule_defs=define_bar_schedules(),
        partition_set_defs=define_baz_partitions(),
    )


@solid
def spew(context):
    context.log.info('HELLO WORLD')


@solid
def fail(context):
    raise Exception('I AM SUPPOSED TO FAIL')


@pipeline
def stdout_pipeline():
    spew()


@pipeline
def stderr_pipeline():
    fail()


def test_list_command():
    runner = CliRunner()

    execute_list_command(
        {
            'repository_yaml': None,
            'python_file': file_relative_path(__file__, 'test_cli_commands.py'),
            'module_name': None,
            'fn_name': 'define_bar_repo',
        },
        no_print,
    )

    result = runner.invoke(
        pipeline_list_command,
        ['-f', file_relative_path(__file__, 'test_cli_commands.py'), '-n', 'define_bar_repo'],
    )

    assert result.exit_code == 0
    assert result.output == (
        'Repository bar\n'
        '**************\n'
        'Pipeline: baz\n'
        'Description:\n'
        'Not much tbh\n'
        'Solids: (Execution Order)\n'
        '    do_input\n'
        '*************\n'
        'Pipeline: foo\n'
        'Solids: (Execution Order)\n'
        '    do_something\n'
        '    do_input\n'
    )

    execute_list_command(
        {
            'repository_yaml': None,
            'python_file': None,
            'module_name': 'dagster_examples.intro_tutorial.repos',
            'fn_name': 'define_repo',
        },
        no_print,
    )

    result = runner.invoke(
        pipeline_list_command, ['-m', 'dagster_examples.intro_tutorial.repos', '-n', 'define_repo']
    )
    assert result.exit_code == 0
    assert result.output == (
        'Repository hello_cereal_repository\n'
        '**********************************\n'
        'Pipeline: complex_pipeline\n'
        'Solids: (Execution Order)\n'
        '    load_cereals\n'
        '    sort_by_calories\n'
        '    sort_by_protein\n'
        '    display_results\n'
        '*******************************\n'
        'Pipeline: hello_cereal_pipeline\n'
        'Solids: (Execution Order)\n'
        '    hello_cereal\n'
    )

    execute_list_command(
        {
            'repository_yaml': file_relative_path(__file__, 'repository_module.yaml'),
            'python_file': None,
            'module_name': None,
            'fn_name': None,
        },
        no_print,
    )

    result = runner.invoke(
        pipeline_list_command, ['-y', file_relative_path(__file__, 'repository_module.yaml')]
    )
    assert result.exit_code == 0
    assert result.output == (
        'Repository hello_cereal_repository\n'
        '**********************************\n'
        'Pipeline: complex_pipeline\n'
        'Solids: (Execution Order)\n'
        '    load_cereals\n'
        '    sort_by_calories\n'
        '    sort_by_protein\n'
        '    display_results\n'
        '*******************************\n'
        'Pipeline: hello_cereal_pipeline\n'
        'Solids: (Execution Order)\n'
        '    hello_cereal\n'
    )

    with pytest.raises(UsageError):
        execute_list_command(
            {
                'repository_yaml': None,
                'python_file': 'foo.py',
                'module_name': 'dagster_examples.intro_tutorial.repos',
                'fn_name': 'define_repo',
            },
            no_print,
        )

    result = runner.invoke(
        pipeline_list_command,
        ['-f', 'foo.py', '-m', 'dagster_examples.intro_tutorial.repos', '-n', 'define_repo'],
    )
    assert result.exit_code == 2

    with pytest.raises(UsageError):
        execute_list_command(
            {
                'repository_yaml': None,
                'python_file': None,
                'module_name': 'dagster_examples.intro_tutorial.repos',
                'fn_name': None,
            },
            no_print,
        )

    result = runner.invoke(pipeline_list_command, ['-m', 'dagster_examples.intro_tutorial.repos'])
    assert result.exit_code == 2

    with pytest.raises(UsageError):
        execute_list_command(
            {
                'repository_yaml': None,
                'python_file': file_relative_path(__file__, 'test_cli_commands.py'),
                'module_name': None,
                'fn_name': None,
            },
            no_print,
        )

    result = runner.invoke(
        pipeline_list_command, ['-f', file_relative_path(__file__, 'test_cli_commands.py')]
    )
    assert result.exit_code == 2


def valid_execute_args():
    return [
        {
            'repository_yaml': file_relative_path(__file__, 'repository_file.yaml'),
            'pipeline_name': ('foo',),
            'python_file': None,
            'module_name': None,
            'fn_name': None,
        },
        {
            'repository_yaml': file_relative_path(__file__, 'repository_module.yaml'),
            'pipeline_name': ('hello_cereal_pipeline',),
            'python_file': None,
            'module_name': None,
            'fn_name': None,
        },
        {
            'repository_yaml': None,
            'pipeline_name': ('foo',),
            'python_file': file_relative_path(__file__, 'test_cli_commands.py'),
            'module_name': None,
            'fn_name': 'define_bar_repo',
        },
        {
            'repository_yaml': None,
            'pipeline_name': ('hello_cereal_pipeline',),
            'python_file': None,
            'module_name': 'dagster_examples.intro_tutorial.repos',
            'fn_name': 'define_repo',
        },
        {
            'repository_yaml': None,
            'pipeline_name': (),
            'python_file': None,
            'module_name': 'dagster_examples.intro_tutorial.repos',
            'fn_name': 'hello_cereal_pipeline',
        },
        {
            'repository_yaml': None,
            'pipeline_name': (),
            'python_file': file_relative_path(__file__, 'test_cli_commands.py'),
            'module_name': None,
            'fn_name': 'define_foo_pipeline',
        },
        {
            'repository_yaml': None,
            'pipeline_name': (),
            'python_file': file_relative_path(__file__, 'test_cli_commands.py'),
            'module_name': None,
            'fn_name': 'foo_pipeline',
        },
    ]


def valid_cli_args():
    return [
        ['-y', file_relative_path(__file__, 'repository_file.yaml'), 'foo'],
        ['-y', file_relative_path(__file__, 'repository_module.yaml'), 'hello_cereal_pipeline'],
        [
            '-f',
            file_relative_path(__file__, 'test_cli_commands.py'),
            '-n',
            'define_bar_repo',
            'foo',
        ],
        [
            '-m',
            'dagster_examples.intro_tutorial.repos',
            '-n',
            'define_repo',
            'hello_cereal_pipeline',
        ],
        ['-m', 'dagster_examples.intro_tutorial.repos', '-n', 'hello_cereal_pipeline'],
        ['-f', file_relative_path(__file__, 'test_cli_commands.py'), '-n', 'define_foo_pipeline'],
    ]


def test_print_command():
    for cli_args in valid_execute_args():
        execute_print_command(verbose=True, cli_args=cli_args, print_fn=no_print)

    for cli_args in valid_execute_args():
        execute_print_command(verbose=False, cli_args=cli_args, print_fn=no_print)

    runner = CliRunner()

    for cli_args in valid_cli_args():
        result = runner.invoke(pipeline_print_command, cli_args)
        assert result.exit_code == 0

        result = runner.invoke(pipeline_print_command, ['--verbose'] + cli_args)
        assert result.exit_code == 0

    res = runner.invoke(
        pipeline_print_command,
        [
            '--verbose',
            '-f',
            file_relative_path(__file__, 'test_cli_commands.py'),
            '-n',
            'define_bar_repo',
            'baz',
        ],
    )
    assert res.exit_code == 0


def test_execute_mode_command():
    runner = CliRunner()

    add_result = runner_pipeline_execute(
        runner,
        [
            '-y',
            file_relative_path(__file__, '../repository.yaml'),
            '--env',
            file_relative_path(__file__, '../environments/multi_mode_with_resources/add_mode.yaml'),
            '-d',
            'add_mode',
            'multi_mode_with_resources',  # pipeline name
        ],
    )

    assert add_result

    mult_result = runner_pipeline_execute(
        runner,
        [
            '-y',
            file_relative_path(__file__, '../repository.yaml'),
            '--env',
            file_relative_path(
                __file__, '../environments/multi_mode_with_resources/mult_mode.yaml'
            ),
            '-d',
            'mult_mode',
            'multi_mode_with_resources',  # pipeline name
        ],
    )

    assert mult_result

    double_adder_result = runner_pipeline_execute(
        runner,
        [
            '-y',
            file_relative_path(__file__, '../repository.yaml'),
            '--env',
            file_relative_path(
                __file__, '../environments/multi_mode_with_resources/double_adder_mode.yaml'
            ),
            '-d',
            'double_adder_mode',
            'multi_mode_with_resources',  # pipeline name
        ],
    )

    assert double_adder_result


def test_execute_preset_command():
    runner = CliRunner()
    add_result = runner_pipeline_execute(
        runner,
        [
            '-y',
            file_relative_path(__file__, '../repository.yaml'),
            '-p',
            'add',
            'multi_mode_with_resources',  # pipeline name
        ],
    )

    assert 'PIPELINE_SUCCESS' in add_result.output

    # Can't use -p with --env
    bad_res = runner.invoke(
        pipeline_execute_command,
        [
            '-y',
            file_relative_path(__file__, '../repository.yaml'),
            '-p',
            'add',
            '--env',
            file_relative_path(
                __file__, '../environments/multi_mode_with_resources/double_adder_mode.yaml'
            ),
            'multi_mode_with_resources',  # pipeline name
        ],
    )
    assert bad_res.exit_code == 2


def test_execute_command():
    for cli_args in valid_execute_args():
        execute_execute_command(env=None, cli_args=cli_args)

    for cli_args in valid_execute_args():
        execute_execute_command(
            env=[file_relative_path(__file__, 'default_log_error_env.yaml')], cli_args=cli_args
        )

    runner = CliRunner()

    for cli_args in valid_cli_args():
        runner_pipeline_execute(runner, cli_args)

        runner_pipeline_execute(
            runner, ['--env', file_relative_path(__file__, 'default_log_error_env.yaml')] + cli_args
        )

    res = runner.invoke(
        pipeline_execute_command,
        [
            '-y',
            file_relative_path(__file__, 'repository_module.yaml'),
            'hello_cereal_pipeline',
            'foo',
        ],
    )
    assert res.exit_code == 1
    assert isinstance(res.exception, CheckError)
    assert 'Can only handle zero or one pipeline args.' in str(res.exception)


def test_stdout_execute_command():
    runner = CliRunner()
    result = runner_pipeline_execute(
        runner,
        ['-f', file_relative_path(__file__, 'test_cli_commands.py'), '-n', 'stdout_pipeline'],
    )
    assert 'HELLO WORLD' in result.output


def test_stderr_execute_command():
    runner = CliRunner()
    result = runner_pipeline_execute(
        runner,
        ['-f', file_relative_path(__file__, 'test_cli_commands.py'), '-n', 'stderr_pipeline'],
    )
    assert 'I AM SUPPOSED TO FAIL' in result.output


def test_fn_not_found_execute():
    with pytest.raises(
        DagsterInvariantViolationError, match='nope not found at module scope in file'
    ):
        execute_execute_command(
            env=None,
            cli_args={
                'repository_yaml': None,
                'pipeline_name': (),
                'python_file': file_relative_path(__file__, 'test_cli_commands.py'),
                'module_name': None,
                'fn_name': 'nope',
            },
        )


def not_a_repo_or_pipeline_fn():
    return 'kdjfkjdf'


not_a_repo_or_pipeline = 123


def test_fn_is_wrong_thing():
    with pytest.raises(
        DagsterInvariantViolationError, match='must resolve to a PipelineDefinition',
    ):
        execute_execute_command(
            env=[],
            cli_args={
                'repository_yaml': None,
                'pipeline_name': (),
                'python_file': file_relative_path(__file__, 'test_cli_commands.py'),
                'module_name': None,
                'fn_name': 'not_a_repo_or_pipeline',
            },
        )


def test_fn_returns_wrong_thing():
    with pytest.raises(
        DagsterInvariantViolationError, match='must resolve to a PipelineDefinition',
    ):
        execute_execute_command(
            env=[],
            cli_args={
                'repository_yaml': None,
                'pipeline_name': (),
                'python_file': file_relative_path(__file__, 'test_cli_commands.py'),
                'module_name': None,
                'fn_name': 'not_a_repo_or_pipeline_fn',
            },
        )


def runner_pipeline_execute(runner, cli_args):
    result = runner.invoke(pipeline_execute_command, cli_args)
    if result.exit_code != 0:
        # CliRunner captures stdout so printing it out here
        raise Exception(
            (
                'dagster pipeline execute commands with cli_args {cli_args} '
                'returned exit_code {exit_code} with stdout:\n"{stdout}" and '
                '\nresult as string: "{result}"'
            ).format(
                cli_args=cli_args, exit_code=result.exit_code, stdout=result.stdout, result=result
            )
        )
    return result


def test_scaffold_command():
    for cli_args in valid_execute_args():
        cli_args['print_only_required'] = True
        execute_scaffold_command(cli_args=cli_args, print_fn=no_print)

        cli_args['print_only_required'] = False
        execute_scaffold_command(cli_args=cli_args, print_fn=no_print)

    runner = CliRunner()

    for cli_args in valid_cli_args():
        result = runner.invoke(pipeline_scaffold_command, cli_args)
        assert result.exit_code == 0

        result = runner.invoke(pipeline_scaffold_command, ['-p'] + cli_args)
        assert result.exit_code == 0


def test_default_memory_run_storage():
    cli_args = {
        'repository_yaml': file_relative_path(__file__, 'repository_file.yaml'),
        'pipeline_name': ('foo',),
        'python_file': None,
        'module_name': None,
        'fn_name': None,
    }
    result = execute_execute_command(env=None, cli_args=cli_args)
    assert result.success


def test_override_with_in_memory_storage():
    cli_args = {
        'repository_yaml': file_relative_path(__file__, 'repository_file.yaml'),
        'pipeline_name': ('foo',),
        'python_file': None,
        'module_name': None,
        'fn_name': None,
    }
    result = execute_execute_command(
        env=[file_relative_path(__file__, 'in_memory_env.yaml')], cli_args=cli_args
    )
    assert result.success


def test_override_with_filesystem_storage():
    cli_args = {
        'repository_yaml': file_relative_path(__file__, 'repository_file.yaml'),
        'pipeline_name': ('foo',),
        'python_file': None,
        'module_name': None,
        'fn_name': None,
    }
    result = execute_execute_command(
        env=[file_relative_path(__file__, 'filesystem_env.yaml')], cli_args=cli_args
    )
    assert result.success


def test_run_list():
    runner = CliRunner()
    result = runner.invoke(run_list_command)
    assert result.exit_code == 0


def test_run_wipe_correct_delete_message():
    runner = CliRunner()
    result = runner.invoke(run_wipe_command, input="DELETE\n")
    assert 'Deleted all run history and event logs' in result.output
    assert result.exit_code == 0


def test_run_wipe_incorrect_delete_message():
    runner = CliRunner()
    result = runner.invoke(run_wipe_command, input="WRONG\n")
    assert 'Exiting without deleting all run history and event logs' in result.output
    assert result.exit_code == 0


def define_bar_schedules():
    return [
        ScheduleDefinition(
            "foo_schedule",
            cron_schedule="* * * * *",
            pipeline_name="test_pipeline",
            environment_dict={},
        )
    ]


@pytest.fixture(name="scheduler_instance")
def define_scheduler_instance():
    with seven.TemporaryDirectory() as temp_dir:
        yield DagsterInstance(
            instance_type=InstanceType.EPHEMERAL,
            local_artifact_storage=LocalArtifactStorage(temp_dir),
            run_storage=InMemoryRunStorage(),
            event_storage=InMemoryEventLogStorage(),
            schedule_storage=SqliteScheduleStorage.from_local(temp_dir),
            scheduler=FilesystemTestScheduler(temp_dir),
            compute_log_manager=NoOpComputeLogManager(temp_dir),
            run_launcher=SyncInMemoryRunLauncher(),
        )


@pytest.fixture(name="_patch_scheduler_instance")
def mock_scheduler_instance(mocker, scheduler_instance):
    mocker.patch(
        'dagster.core.instance.DagsterInstance.get', return_value=scheduler_instance,
    )


def test_schedules_list(_patch_scheduler_instance):
    runner = CliRunner()

    result = runner.invoke(
        schedule_list_command, ['-y', file_relative_path(__file__, 'repository_file.yaml')]
    )

    if result.exception:
        raise result.exception

    assert result.exit_code == 0
    assert result.output == ('Repository bar\n' '**************\n')


def test_schedules_up(_patch_scheduler_instance):
    runner = CliRunner()

    result = runner.invoke(
        schedule_up_command, ['-y', file_relative_path(__file__, 'repository_file.yaml')]
    )

    assert result.exit_code == 0
    assert result.output == 'Changes:\n  + foo_schedule (add)\n'


def test_schedules_up_and_list(_patch_scheduler_instance):
    runner = CliRunner()

    result = runner.invoke(
        schedule_up_command, ['-y', file_relative_path(__file__, 'repository_file.yaml')]
    )

    result = runner.invoke(
        schedule_list_command, ['-y', file_relative_path(__file__, 'repository_file.yaml')]
    )

    assert result.exit_code == 0
    assert (
        result.output == 'Repository bar\n'
        '**************\n'
        'Schedule: foo_schedule [STOPPED]\n'
        'Cron Schedule: * * * * *\n'
    )


def test_schedules_start_and_stop(_patch_scheduler_instance):
    runner = CliRunner()

    result = runner.invoke(
        schedule_up_command, ['-y', file_relative_path(__file__, 'repository_file.yaml')],
    )

    result = runner.invoke(
        schedule_start_command,
        ['-y', file_relative_path(__file__, 'repository_file.yaml'), 'foo_schedule'],
    )

    assert result.exit_code == 0
    assert 'Started schedule foo_schedule\n' == result.output

    result = runner.invoke(
        schedule_stop_command,
        ['-y', file_relative_path(__file__, 'repository_file.yaml'), 'foo_schedule'],
    )

    assert result.exit_code == 0
    assert 'Stopped schedule foo_schedule\n' == result.output


def test_schedules_start_empty(_patch_scheduler_instance):
    runner = CliRunner()

    result = runner.invoke(
        schedule_start_command, ['-y', file_relative_path(__file__, 'repository_file.yaml')],
    )

    assert result.exit_code == 0
    assert 'Noop: dagster schedule start was called without any arguments' in result.output


def test_schedules_start_all(_patch_scheduler_instance):
    runner = CliRunner()

    result = runner.invoke(
        schedule_up_command, ['-y', file_relative_path(__file__, 'repository_file.yaml')]
    )

    result = runner.invoke(
        schedule_start_command,
        ['-y', file_relative_path(__file__, 'repository_file.yaml'), '--start-all'],
    )

    assert result.exit_code == 0
    assert result.output == 'Started all schedules for repository bar\n'


def test_schedules_wipe_correct_delete_message(_patch_scheduler_instance):
    runner = CliRunner()

    result = runner.invoke(
        schedule_up_command, ['-y', file_relative_path(__file__, 'repository_file.yaml')]
    )

    result = runner.invoke(
        schedule_wipe_command,
        ['-y', file_relative_path(__file__, 'repository_file.yaml')],
        input="DELETE\n",
    )

    if result.exception:
        raise result.exception

    assert result.exit_code == 0
    assert 'Wiped all schedules and schedule cron jobs' in result.output

    result = runner.invoke(
        schedule_up_command,
        ['-y', file_relative_path(__file__, 'repository_file.yaml'), '--preview'],
    )

    # Verify schedules were wiped
    assert result.exit_code == 0
    assert result.output == 'Planned Changes:\n  + foo_schedule (add)\n'


def test_schedules_wipe_incorrect_delete_message(_patch_scheduler_instance):
    runner = CliRunner()

    result = runner.invoke(
        schedule_up_command, ['-y', file_relative_path(__file__, 'repository_file.yaml')]
    )

    result = runner.invoke(
        schedule_wipe_command,
        ['-y', file_relative_path(__file__, 'repository_file.yaml')],
        input="WRONG\n",
    )

    assert result.exit_code == 0
    assert 'Exiting without deleting all schedules and schedule cron jobs' in result.output

    result = runner.invoke(
        schedule_up_command,
        ['-y', file_relative_path(__file__, 'repository_file.yaml'), '--preview'],
    )

    # Verify schedules were not wiped
    assert result.exit_code == 0
    assert result.output == 'No planned changes to schedules.\n1 schedules will remain unchanged\n'


def test_schedules_restart(_patch_scheduler_instance):
    runner = CliRunner()

    result = runner.invoke(
        schedule_up_command, ['-y', file_relative_path(__file__, 'repository_file.yaml')]
    )

    result = runner.invoke(
        schedule_start_command,
        ['-y', file_relative_path(__file__, 'repository_file.yaml'), 'foo_schedule'],
    )

    result = runner.invoke(
        schedule_restart_command,
        ['-y', file_relative_path(__file__, 'repository_file.yaml'), 'foo_schedule'],
    )

    assert result.exit_code == 0
    assert 'Restarted schedule foo_schedule' in result.output


def test_schedules_restart_all(_patch_scheduler_instance):
    runner = CliRunner()

    result = runner.invoke(
        schedule_up_command, ['-y', file_relative_path(__file__, 'repository_file.yaml')]
    )

    result = runner.invoke(
        schedule_start_command,
        ['-y', file_relative_path(__file__, 'repository_file.yaml'), 'foo_schedule'],
    )

    result = runner.invoke(
        schedule_restart_command,
        [
            '-y',
            file_relative_path(__file__, 'repository_file.yaml'),
            'foo_schedule',
            '--restart-all-running',
        ],
    )

    assert result.exit_code == 0
    assert result.output == 'Restarted all running schedules for repository bar\n'


@pytest.mark.skipif(
    os.name == 'nt', reason="multiproc directory test disabled for windows because of fs contention"
)
def test_multiproc():
    with seven.TemporaryDirectory() as temp:
        runner = CliRunner(env={'DAGSTER_HOME': temp})
        add_result = runner_pipeline_execute(
            runner,
            [
                '-y',
                file_relative_path(__file__, '../repository.yaml'),
                '-p',
                'multiproc',
                'multi_mode_with_resources',  # pipeline name
            ],
        )
        assert 'PIPELINE_SUCCESS' in add_result.output


def test_multiproc_invalid():
    # force ephemeral instance by removing out DAGSTER_HOME
    runner = CliRunner(env={'DAGSTER_HOME': None})
    add_result = runner_pipeline_execute(
        runner,
        [
            '-y',
            file_relative_path(__file__, '../repository.yaml'),
            '-p',
            'multiproc',
            'multi_mode_with_resources',  # pipeline name
        ],
    )
    # which is invalid for multiproc
    assert 'DagsterUnmetExecutorRequirementsError' in add_result.output


class InMemoryRunLauncher(RunLauncher, ConfigurableClass):
    def __init__(self, inst_data=None):
        self._inst_data = inst_data
        self._queue = []

    def launch_run(self, instance, run, external_pipeline=None):
        self._queue.append(run)
        return run

    def queue(self):
        return self._queue

    @classmethod
    def config_type(cls):
        return Shape({})

    @classmethod
    def from_config_value(cls, inst_data, config_value):
        return cls(inst_data=inst_data,)

    @property
    def inst_data(self):
        return self._inst_data

    def can_terminate(self, run_id):
        return False

    def terminate(self, run_id):
        check.not_implemented('Termintation not supported')


def define_baz_partitions():
    return [
        PartitionSetDefinition(
            name='baz_partitions',
            pipeline_name='baz',
            partition_fn=lambda: string.ascii_lowercase,
            environment_dict_fn_for_partition=lambda partition: {
                'solids': {'do_input': {'inputs': {'x': {'value': partition}}}}
            },
        )
    ]


def backfill_execute_args(execution_args):
    backfill_args = {
        'repository_yaml': file_relative_path(__file__, 'repository_file.yaml'),
        'noprompt': True,
    }
    pipeline_name = execution_args.get('pipeline_name')
    if pipeline_name:
        backfill_args['pipeline_name'] = (pipeline_name,)
    for name, value in execution_args.items():
        if name != 'pipeline_name':
            backfill_args[name] = value
    return backfill_args


def backfill_cli_runner_args(execution_args):
    backfill_args = ['-y', file_relative_path(__file__, 'repository_file.yaml'), '--noprompt']
    pipeline_name = execution_args.get('pipeline_name')
    if pipeline_name:
        backfill_args.append(pipeline_name)
    for name, value in execution_args.items():
        if name != 'pipeline_name':
            backfill_args.extend(['--{}'.format(name.replace('_', '-')), value])
    return backfill_args


def run_test_backfill(execution_args, expected_count=None, error_message=None):
    runner = CliRunner()
    run_launcher = InMemoryRunLauncher()
    with seven.TemporaryDirectory() as temp_dir:
        instance = DagsterInstance(
            instance_type=InstanceType.EPHEMERAL,
            local_artifact_storage=LocalArtifactStorage(temp_dir),
            run_storage=InMemoryRunStorage(),
            event_storage=InMemoryEventLogStorage(),
            compute_log_manager=NoOpComputeLogManager(temp_dir),
            run_launcher=run_launcher,
        )
        with mock.patch('dagster.core.instance.DagsterInstance.get') as _instance:
            _instance.return_value = instance

            if error_message:
                with pytest.raises(UsageError) as error_info:
                    execute_backfill_command(backfill_execute_args(execution_args), no_print)
                assert error_info and error_message in error_info.value.message

            result = runner.invoke(
                pipeline_backfill_command, backfill_cli_runner_args(execution_args)
            )
            if error_message:
                assert result.exit_code == 2
            else:
                assert result.exit_code == 0
                if expected_count:
                    assert len(run_launcher.queue()) == expected_count


def test_backfill_no_pipeline():
    args = {'pipeline_name': 'nonexistent'}
    run_test_backfill(args, error_message='No pipeline found')


def test_backfill_no_partition_sets():
    args = {'pipeline_name': 'foo'}
    run_test_backfill(args, error_message='No partition sets found')


def test_backfill_no_named_partition_set():
    args = {'pipeline_name': 'baz', 'partition_set': 'nonexistent'}
    run_test_backfill(args, error_message='No partition set found')


def test_backfill_launch():
    args = {'pipeline_name': 'baz', 'partition_set': 'baz_partitions'}
    run_test_backfill(args, expected_count=len(string.ascii_lowercase))


def test_backfill_partition_range():
    args = {'pipeline_name': 'baz', 'partition_set': 'baz_partitions', 'from': 'x'}
    run_test_backfill(args, expected_count=3)

    args = {'pipeline_name': 'baz', 'partition_set': 'baz_partitions', 'to': 'c'}
    run_test_backfill(args, expected_count=3)

    args = {'pipeline_name': 'baz', 'partition_set': 'baz_partitions', 'from': 'c', 'to': 'f'}
    run_test_backfill(args, expected_count=4)


def test_backfill_partition_enum():
    args = {'pipeline_name': 'baz', 'partition_set': 'baz_partitions', 'partitions': 'c,x,z'}
    run_test_backfill(args, expected_count=3)


def run_launch(execution_args, expected_count=None):
    runner = CliRunner()
    run_launcher = InMemoryRunLauncher()
    with seven.TemporaryDirectory() as temp_dir:
        instance = DagsterInstance(
            instance_type=InstanceType.EPHEMERAL,
            local_artifact_storage=LocalArtifactStorage(temp_dir),
            run_storage=InMemoryRunStorage(),
            event_storage=InMemoryEventLogStorage(),
            compute_log_manager=NoOpComputeLogManager(temp_dir),
            run_launcher=run_launcher,
        )
        with mock.patch('dagster.core.instance.DagsterInstance.get') as _instance:
            _instance.return_value = instance

            result = runner.invoke(pipeline_launch_command, execution_args)
            assert result.exit_code == 0
            if expected_count:
                assert len(run_launcher.queue()) == expected_count


def test_launch_pipeline():
    for cli_args in valid_cli_args():
        run_launch(cli_args, expected_count=1)


@contextmanager
def mocked_instance():
    with seven.TemporaryDirectory() as temp_dir:
        instance = DagsterInstance(
            instance_type=InstanceType.EPHEMERAL,
            local_artifact_storage=LocalArtifactStorage(temp_dir),
            run_storage=InMemoryRunStorage(),
            event_storage=InMemoryEventLogStorage(),
            compute_log_manager=NoOpComputeLogManager(temp_dir),
            run_launcher=InMemoryRunLauncher(),
        )
        with mock.patch('dagster.core.instance.DagsterInstance.get') as _instance:
            _instance.return_value = instance
            yield instance


def test_tags_pipeline():
    runner = CliRunner()
    with mocked_instance() as instance:
        result = runner.invoke(
            pipeline_execute_command,
            [
                '-y',
                file_relative_path(__file__, 'repository_module.yaml'),
                '--tags',
                '{ "foo": "bar" }',
                'hello_cereal_pipeline',
            ],
        )
        assert result.exit_code == 0
        runs = instance.get_runs()
        assert len(runs) == 1
        run = runs[0]
        assert len(run.tags) == 1
        assert run.tags.get('foo') == 'bar'

    with mocked_instance() as instance:
        result = runner.invoke(
            pipeline_execute_command,
            [
                '-y',
                file_relative_path(__file__, '../repository.yaml'),
                '-p',
                'add',
                '--tags',
                '{ "foo": "bar" }',
                'multi_mode_with_resources',  # pipeline name
            ],
        )
        assert result.exit_code == 0
        runs = instance.get_runs()
        assert len(runs) == 1
        run = runs[0]
        assert len(run.tags) == 1
        assert run.tags.get('foo') == 'bar'

    with mocked_instance() as instance:
        result = runner.invoke(
            pipeline_backfill_command,
            [
                '-y',
                file_relative_path(__file__, 'repository_file.yaml'),
                '--noprompt',
                '--partition-set',
                'baz_partitions',
                '--partitions',
                'c',
                '--tags',
                '{ "foo": "bar" }',
                'baz',
            ],
        )
        assert result.exit_code == 0
        runs = instance.run_launcher.queue()
        assert len(runs) == 1
        run = runs[0]
        assert len(run.tags) >= 1
        assert run.tags.get('foo') == 'bar'
