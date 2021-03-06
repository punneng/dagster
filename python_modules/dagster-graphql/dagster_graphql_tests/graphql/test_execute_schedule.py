import time
import uuid

import pytest
from dagster_graphql.test.utils import execute_dagster_graphql_and_finish_runs

from dagster.core.scheduler import reconcile_scheduler_state
from dagster.core.scheduler.scheduler import ScheduleTickStatus

from .execution_queries import START_SCHEDULED_EXECUTION_QUERY
from .graphql_context_test_suite import GraphQLContextVariant, make_graphql_context_test_suite
from .utils import get_all_logs_for_finished_run_via_subscription

SCHEDULE_TICKS_QUERY = '''
{
    scheduler {
    ... on PythonError {
        message
        stack
    }
    ... on Scheduler {
        runningSchedules {
            scheduleDefinition {
                name
            }
            ticks {
                tickId
                status
            }
            stats {
                ticksStarted
                ticksSucceeded
                ticksSkipped
                ticksFailed
            }
            ticksCount
        }
    }
    }
}
'''


def assert_start_scheduled_execution_success(result):
    assert result.data['startScheduledExecution']['__typename'] in {
        'StartPipelineRunSuccess',
        'LaunchPipelineRunSuccess',
    }


class TestExecuteSchedule(
    # Event with the test matrices, testing all the variants is still
    # too slow. Going to focus on the most common prod cases for now
    # and the things are most relevant to the transition.
    make_graphql_context_test_suite(
        context_variants=[GraphQLContextVariant.sqlite_with_cli_api_run_launcher_in_process_env()]
    )
):
    def test_just_basic_start_scheduled_execution(self, graphql_context):
        result = execute_dagster_graphql_and_finish_runs(
            graphql_context,
            START_SCHEDULED_EXECUTION_QUERY,
            variables={'scheduleName': 'no_config_pipeline_hourly_schedule'},
        )

        assert not result.errors
        assert result.data
        assert_start_scheduled_execution_success(result)

        assert uuid.UUID(result.data['startScheduledExecution']['run']['runId'])
        assert (
            result.data['startScheduledExecution']['run']['pipeline']['name']
            == 'no_config_pipeline'
        )

        assert any(
            tag['key'] == 'dagster/schedule_name'
            and tag['value'] == 'no_config_pipeline_hourly_schedule'
            for tag in result.data['startScheduledExecution']['run']['tags']
        )

    def test_basic_start_scheduled_execution_with_run_launcher(self, graphql_context):
        result = execute_dagster_graphql_and_finish_runs(
            graphql_context,
            START_SCHEDULED_EXECUTION_QUERY,
            variables={'scheduleName': 'no_config_pipeline_hourly_schedule'},
        )

        assert not result.errors
        assert result.data

        # just test existence
        assert_start_scheduled_execution_success(result)

        assert uuid.UUID(result.data['startScheduledExecution']['run']['runId'])
        assert (
            result.data['startScheduledExecution']['run']['pipeline']['name']
            == 'no_config_pipeline'
        )

        assert any(
            tag['key'] == 'dagster/schedule_name'
            and tag['value'] == 'no_config_pipeline_hourly_schedule'
            for tag in result.data['startScheduledExecution']['run']['tags']
        )

    def test_basic_start_scheduled_execution_with_environment_dict_fn(self, graphql_context):
        result = execute_dagster_graphql_and_finish_runs(
            graphql_context,
            START_SCHEDULED_EXECUTION_QUERY,
            variables={'scheduleName': 'no_config_pipeline_hourly_schedule_with_config_fn'},
        )

        assert not result.errors
        assert result.data

        # just test existence
        assert_start_scheduled_execution_success(result)

        assert uuid.UUID(result.data['startScheduledExecution']['run']['runId'])
        assert (
            result.data['startScheduledExecution']['run']['pipeline']['name']
            == 'no_config_pipeline'
        )

        assert any(
            tag['key'] == 'dagster/schedule_name'
            and tag['value'] == 'no_config_pipeline_hourly_schedule_with_config_fn'
            for tag in result.data['startScheduledExecution']['run']['tags']
        )

    def test_start_scheduled_execution_with_should_execute(self, graphql_context):
        result = execute_dagster_graphql_and_finish_runs(
            graphql_context,
            START_SCHEDULED_EXECUTION_QUERY,
            variables={'scheduleName': 'no_config_should_execute'},
        )

        assert not result.errors
        assert result.data

        assert result.data['startScheduledExecution']['__typename'] == 'ScheduledExecutionBlocked'

    def test_partition_based_execution(self, graphql_context):
        result = execute_dagster_graphql_and_finish_runs(
            graphql_context,
            START_SCHEDULED_EXECUTION_QUERY,
            variables={'scheduleName': 'partition_based'},
        )

        assert not result.errors
        assert result.data

        # just test existence
        assert_start_scheduled_execution_success(result)

        assert uuid.UUID(result.data['startScheduledExecution']['run']['runId'])
        assert (
            result.data['startScheduledExecution']['run']['pipeline']['name']
            == 'no_config_pipeline'
        )

        tags = result.data['startScheduledExecution']['run']['tags']

        assert any(
            tag['key'] == 'dagster/schedule_name' and tag['value'] == 'partition_based'
            for tag in tags
        )

        assert any(tag['key'] == 'dagster/partition' and tag['value'] == '9' for tag in tags)
        assert any(
            tag['key'] == 'dagster/partition_set' and tag['value'] == 'scheduled_integer_partitions'
            for tag in tags
        )

        result_two = execute_dagster_graphql_and_finish_runs(
            graphql_context,
            START_SCHEDULED_EXECUTION_QUERY,
            variables={'scheduleName': 'partition_based'},
        )
        tags = result_two.data['startScheduledExecution']['run']['tags']
        # the last partition is selected on subsequent runs
        assert any(tag['key'] == 'dagster/partition' and tag['value'] == '9' for tag in tags)

    def test_partition_based_custom_selector(self, graphql_context):
        result = execute_dagster_graphql_and_finish_runs(
            graphql_context,
            START_SCHEDULED_EXECUTION_QUERY,
            variables={'scheduleName': 'partition_based_custom_selector'},
        )

        assert not result.errors
        assert result.data
        assert_start_scheduled_execution_success(result)
        assert uuid.UUID(result.data['startScheduledExecution']['run']['runId'])
        assert (
            result.data['startScheduledExecution']['run']['pipeline']['name']
            == 'no_config_pipeline'
        )
        tags = result.data['startScheduledExecution']['run']['tags']
        assert any(
            tag['key'] == 'dagster/schedule_name'
            and tag['value'] == 'partition_based_custom_selector'
            for tag in tags
        )
        assert any(tag['key'] == 'dagster/partition' and tag['value'] == '9' for tag in tags)
        assert any(
            tag['key'] == 'dagster/partition_set' and tag['value'] == 'scheduled_integer_partitions'
            for tag in tags
        )

        result_two = execute_dagster_graphql_and_finish_runs(
            graphql_context,
            START_SCHEDULED_EXECUTION_QUERY,
            variables={'scheduleName': 'partition_based_custom_selector'},
        )
        tags = result_two.data['startScheduledExecution']['run']['tags']
        # get a different partition based on the subsequent run storage

        assert any(tag['key'] == 'dagster/partition' and tag['value'] == '8' for tag in tags)

    def test_partition_based_decorator(self, graphql_context):
        result = execute_dagster_graphql_and_finish_runs(
            graphql_context,
            START_SCHEDULED_EXECUTION_QUERY,
            variables={'scheduleName': 'partition_based_decorator'},
        )

        assert not result.errors
        assert result.data
        assert_start_scheduled_execution_success(result)

    @pytest.mark.parametrize(
        'schedule_name',
        [
            'solid_subset_hourly_decorator',
            'solid_subset_daily_decorator',
            'solid_subset_monthly_decorator',
            'solid_subset_weekly_decorator',
        ],
    )
    def test_solid_subset_schedule_decorator(self, schedule_name, graphql_context):
        result = execute_dagster_graphql_and_finish_runs(
            graphql_context,
            START_SCHEDULED_EXECUTION_QUERY,
            variables={'scheduleName': schedule_name},
        )

        assert not result.errors
        assert result.data
        assert_start_scheduled_execution_success(result)

        run_id = result.data['startScheduledExecution']['run']['runId']

        logs = get_all_logs_for_finished_run_via_subscription(graphql_context, run_id)[
            'pipelineRunLogs'
        ]['messages']
        execution_step_names = [
            log['step']['key'] for log in logs if log['__typename'] == 'ExecutionStepStartEvent'
        ]
        assert execution_step_names == ['return_foo.compute']

    def test_partition_based_multi_mode_decorator(self, graphql_context):
        result = execute_dagster_graphql_and_finish_runs(
            graphql_context,
            START_SCHEDULED_EXECUTION_QUERY,
            variables={'scheduleName': 'partition_based_multi_mode_decorator'},
        )

        assert not result.errors
        assert result.data
        assert_start_scheduled_execution_success(result)
        run_id = result.data['startScheduledExecution']['run']['runId']

        logs = get_all_logs_for_finished_run_via_subscription(graphql_context, run_id)[
            'pipelineRunLogs'
        ]['messages']
        execution_step_names = [
            log['step']['key'] for log in logs if log['__typename'] == 'ExecutionStepStartEvent'
        ]
        assert execution_step_names == ['return_six.compute']

    # Tests for ticks and execution user error boundary
    def test_tick_success(self, graphql_context, snapshot):
        context = graphql_context
        instance = context.instance

        repository = context.legacy_get_repository_definition()

        reconcile_scheduler_state("", "", repository, instance)
        schedule_def = repository.get_schedule_def("no_config_pipeline_hourly_schedule")

        start_time = time.time()
        execute_dagster_graphql_and_finish_runs(
            context, START_SCHEDULED_EXECUTION_QUERY, variables={'scheduleName': schedule_def.name},
        )

        # Check tick data and stats through gql
        result = execute_dagster_graphql_and_finish_runs(context, SCHEDULE_TICKS_QUERY)

        assert result.data
        schedule_result = next(
            schedule_result
            for schedule_result in result.data['scheduler']['runningSchedules']
            if schedule_result['scheduleDefinition']['name'] == schedule_def.name
        )

        assert schedule_result
        assert schedule_result['stats']['ticksSucceeded'] == 1
        snapshot.assert_match(schedule_result)

        # Check directly against the DB
        ticks = instance.get_schedule_ticks_by_schedule(repository.name, schedule_def.name)
        assert len(ticks) == 1
        tick = ticks[0]
        assert tick.schedule_name == schedule_def.name
        assert tick.cron_schedule == schedule_def.cron_schedule
        assert tick.timestamp > start_time and tick.timestamp < time.time()
        assert tick.status == ScheduleTickStatus.SUCCESS
        assert tick.run_id

    def test_tick_skip(self, graphql_context, snapshot):
        instance = graphql_context.instance

        repository = graphql_context.legacy_get_repository_definition()
        reconcile_scheduler_state("", "", repository, instance)

        execute_dagster_graphql_and_finish_runs(
            graphql_context,
            START_SCHEDULED_EXECUTION_QUERY,
            variables={'scheduleName': 'no_config_should_execute'},
        )

        # Check tick data and stats through gql
        result = execute_dagster_graphql_and_finish_runs(graphql_context, SCHEDULE_TICKS_QUERY)
        schedule_result = next(
            x
            for x in result.data['scheduler']['runningSchedules']
            if x['scheduleDefinition']['name'] == 'no_config_should_execute'
        )
        assert schedule_result['stats']['ticksSkipped'] == 1
        snapshot.assert_match(schedule_result)

        ticks = instance.get_schedule_ticks_by_schedule(repository.name, 'no_config_should_execute')

        assert len(ticks) == 1
        tick = ticks[0]
        assert tick.status == ScheduleTickStatus.SKIPPED

    def test_should_execute_scheduler_error(self, graphql_context, snapshot):
        instance = graphql_context.instance
        repository = graphql_context.legacy_get_repository_definition()
        reconcile_scheduler_state("", "", repository, instance)

        execute_dagster_graphql_and_finish_runs(
            graphql_context,
            START_SCHEDULED_EXECUTION_QUERY,
            variables={'scheduleName': 'should_execute_error_schedule'},
        )

        # Check tick data and stats through gql
        result = execute_dagster_graphql_and_finish_runs(graphql_context, SCHEDULE_TICKS_QUERY)
        schedule_result = next(
            x
            for x in result.data['scheduler']['runningSchedules']
            if x['scheduleDefinition']['name'] == 'should_execute_error_schedule'
        )
        assert schedule_result['stats']['ticksFailed'] == 1
        snapshot.assert_match(schedule_result)

        ticks = instance.get_schedule_ticks_by_schedule(
            repository.name, 'should_execute_error_schedule'
        )

        assert len(ticks) == 1
        tick = ticks[0]
        assert tick.status == ScheduleTickStatus.FAILURE
        assert tick.error
        assert (
            "Error occurred during the execution should_execute for schedule "
            "should_execute_error_schedule" in tick.error.message
        )

    def test_tags_scheduler_error(self, graphql_context, snapshot):
        instance = graphql_context.instance
        repository = graphql_context.legacy_get_repository_definition()
        reconcile_scheduler_state("", "", repository, instance)

        result = execute_dagster_graphql_and_finish_runs(
            graphql_context,
            START_SCHEDULED_EXECUTION_QUERY,
            variables={'scheduleName': 'tags_error_schedule'},
        )

        assert_start_scheduled_execution_success(result)
        run_id = result.data['startScheduledExecution']['run']['runId']

        # Check tick data and stats through gql
        result = execute_dagster_graphql_and_finish_runs(graphql_context, SCHEDULE_TICKS_QUERY)
        schedule_result = next(
            x
            for x in result.data['scheduler']['runningSchedules']
            if x['scheduleDefinition']['name'] == 'tags_error_schedule'
        )

        assert schedule_result['stats']['ticksSucceeded'] == 1
        snapshot.assert_match(schedule_result)

        ticks = instance.get_schedule_ticks_by_schedule(repository.name, 'tags_error_schedule')

        assert len(ticks) == 1
        tick = ticks[0]
        assert tick.status == ScheduleTickStatus.SUCCESS
        assert tick.run_id == run_id

    def test_environment_dict_scheduler_error(self, graphql_context, snapshot):
        instance = graphql_context.instance
        repository = graphql_context.legacy_get_repository_definition()
        reconcile_scheduler_state("", "", repository, instance)

        result = execute_dagster_graphql_and_finish_runs(
            graphql_context,
            START_SCHEDULED_EXECUTION_QUERY,
            variables={'scheduleName': 'environment_dict_error_schedule'},
        )
        assert_start_scheduled_execution_success(result)
        run_id = result.data['startScheduledExecution']['run']['runId']

        # Check tick data and stats through gql
        result = execute_dagster_graphql_and_finish_runs(graphql_context, SCHEDULE_TICKS_QUERY)
        schedule_result = next(
            x
            for x in result.data['scheduler']['runningSchedules']
            if x['scheduleDefinition']['name'] == 'environment_dict_error_schedule'
        )
        assert schedule_result['stats']['ticksSucceeded'] == 1
        snapshot.assert_match(schedule_result)

        ticks = instance.get_schedule_ticks_by_schedule(
            repository.name, 'environment_dict_error_schedule'
        )

        assert len(ticks) == 1
        tick = ticks[0]
        assert tick.status == ScheduleTickStatus.SUCCESS
        assert tick.run_id == run_id

    def test_environment_dict_scheduler_error_serialize_cause(self, graphql_context):
        instance = graphql_context.instance
        repository = graphql_context.legacy_get_repository_definition()
        reconcile_scheduler_state("", "", repository, instance)

        result = execute_dagster_graphql_and_finish_runs(
            graphql_context,
            START_SCHEDULED_EXECUTION_QUERY,
            variables={'scheduleName': 'environment_dict_error_schedule'},
        )
        assert_start_scheduled_execution_success(result)
        run_id = result.data['startScheduledExecution']['run']['runId']

        ticks = instance.get_schedule_ticks_by_schedule(
            repository.name, 'environment_dict_error_schedule'
        )

        assert len(ticks) == 1
        tick = ticks[0]
        assert tick.status == ScheduleTickStatus.SUCCESS
        assert tick.run_id == run_id

    def test_query_multiple_schedule_ticks(self, graphql_context, snapshot):
        instance = graphql_context.instance
        repository = graphql_context.legacy_get_repository_definition()
        reconcile_scheduler_state("", "", repository, instance)

        for scheduleName in [
            'no_config_pipeline_hourly_schedule',
            'no_config_should_execute',
            'environment_dict_error_schedule',
        ]:
            execute_dagster_graphql_and_finish_runs(
                graphql_context,
                START_SCHEDULED_EXECUTION_QUERY,
                variables={'scheduleName': scheduleName},
            )

        result = execute_dagster_graphql_and_finish_runs(graphql_context, SCHEDULE_TICKS_QUERY)
        snapshot.assert_match(result.data['scheduler']['runningSchedules'])

    def test_tagged_pipeline_schedule(self, graphql_context):
        result = execute_dagster_graphql_and_finish_runs(
            graphql_context,
            START_SCHEDULED_EXECUTION_QUERY,
            variables={'scheduleName': 'tagged_pipeline_schedule'},
        )

        assert not result.errors
        assert_start_scheduled_execution_success(result)
        assert (
            result.data['startScheduledExecution']['run']['pipeline']['name'] == 'tagged_pipeline'
        )

        assert any(
            tag['key'] == 'foo' and tag['value'] == 'bar'
            for tag in result.data['startScheduledExecution']['run']['tags']
        )

    def test_tagged_pipeline_override_schedule(self, graphql_context):
        result = execute_dagster_graphql_and_finish_runs(
            graphql_context,
            START_SCHEDULED_EXECUTION_QUERY,
            variables={'scheduleName': 'tagged_pipeline_override_schedule'},
        )

        assert not result.errors
        assert_start_scheduled_execution_success(result)
        assert (
            result.data['startScheduledExecution']['run']['pipeline']['name'] == 'tagged_pipeline'
        )

        assert not any(
            tag['key'] == 'foo' and tag['value'] == 'bar'
            for tag in result.data['startScheduledExecution']['run']['tags']
        )
        assert any(
            tag['key'] == 'foo' and tag['value'] == 'notbar'
            for tag in result.data['startScheduledExecution']['run']['tags']
        )

    def test_tagged_pipeline_scheduled_execution_with_run_launcher(self, graphql_context):
        result = execute_dagster_graphql_and_finish_runs(
            graphql_context,
            START_SCHEDULED_EXECUTION_QUERY,
            variables={'scheduleName': 'tagged_pipeline_schedule'},
        )

        assert not result.errors
        assert result.data

        # just test existence
        assert_start_scheduled_execution_success(result)

        assert uuid.UUID(result.data['startScheduledExecution']['run']['runId'])
        assert (
            result.data['startScheduledExecution']['run']['pipeline']['name'] == 'tagged_pipeline'
        )

        assert any(
            tag['key'] == 'foo' and tag['value'] == 'bar'
            for tag in result.data['startScheduledExecution']['run']['tags']
        )

    def test_invalid_config_schedule_error(self, graphql_context, snapshot):
        repository = graphql_context.legacy_get_repository_definition()
        instance = graphql_context.instance
        reconcile_scheduler_state("", "", repository, instance)
        result = execute_dagster_graphql_and_finish_runs(
            graphql_context,
            START_SCHEDULED_EXECUTION_QUERY,
            variables={'scheduleName': 'invalid_config_schedule'},
        )

        assert (
            result.data['startScheduledExecution']['__typename']
            == 'PipelineConfigValidationInvalid'
        )

        # Check tick data and stats through gql
        result = execute_dagster_graphql_and_finish_runs(graphql_context, SCHEDULE_TICKS_QUERY)
        schedule_result = next(
            x
            for x in result.data['scheduler']['runningSchedules']
            if x['scheduleDefinition']['name'] == 'invalid_config_schedule'
        )
        assert schedule_result['stats']['ticksSucceeded'] == 1
        snapshot.assert_match(schedule_result)

        ticks = instance.get_schedule_ticks_by_schedule(repository.name, 'invalid_config_schedule')

        assert len(ticks) == 1
        tick = ticks[0]
        assert tick.status == ScheduleTickStatus.SUCCESS
