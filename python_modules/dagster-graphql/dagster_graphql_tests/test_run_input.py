from dagster_graphql.client.util import execution_params_from_pipeline_run
from dagster_graphql.schema.roots import execution_params_from_graphql
from dagster_graphql.test.utils import define_context_for_file

from dagster import DagsterInstance, pipeline
from dagster.core.storage.pipeline_run import PipelineRun, PipelineRunStatus


@pipeline
def pipey_mcpipeface():
    pass


def test_roundtrip_run():
    run_with_snapshot = PipelineRun(
        pipeline_name='pipey_mcpipeface',
        run_id='8675309',
        environment_dict={'good': True},
        mode='default',
        solid_subset=['solid_1'],
        step_keys_to_execute=['step_1', 'step_2', 'step_3'],
        tags={'tag_it': 'bag_it'},
        status=PipelineRunStatus.NOT_STARTED,
        root_run_id='previousID',
        parent_run_id='previousID',
        pipeline_snapshot_id='pipey_mcpipeface_snapshot_id',
        execution_plan_snapshot_id='mcexecutionplanface_snapshot_id',
    )
    for field in run_with_snapshot:
        # ensure we have a test value to round trip for each field
        assert field

    # The invariant that all the execution parameter structs
    # pipeline run can be constructed from each other is no longer
    # true. Clients of the GraphQL API cannot know the value of the
    # pipeline_snapshot_id prior to execution, because it is
    # constructed on the server. Hence these roundtrip tests
    # do not include snapshot_id

    run = run_with_snapshot._replace(pipeline_snapshot_id=None, execution_plan_snapshot_id=None)

    context = define_context_for_file(__file__, 'pipey_mcpipeface', DagsterInstance.ephemeral())

    exec_params = execution_params_from_pipeline_run(context, run)

    exec_params_gql = execution_params_from_graphql(context, exec_params.to_graphql_input())
    assert exec_params_gql == exec_params

    empty_run = PipelineRun(pipeline_name='foo', run_id='bar', mode='default')
    exec_params = execution_params_from_pipeline_run(context, empty_run)

    exec_params_gql = execution_params_from_graphql(context, exec_params.to_graphql_input())
    assert exec_params_gql == exec_params
