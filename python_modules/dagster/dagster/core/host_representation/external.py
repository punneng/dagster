from collections import OrderedDict

from dagster import check
from dagster.core.snap import ExecutionPlanSnapshot
from dagster.core.utils import toposort

from .external_data import ExternalPipelineData, ExternalRepositoryData
from .handle import PipelineHandle, RepositoryHandle
from .pipeline_index import PipelineIndex
from .represented import RepresentedPipeline


class ExternalRepository:
    '''
    ExternalRepository is a object that represents a loaded repository definition that
    is resident in another process or container. Host processes such as dagit use
    objects such as these to interact with user-defined artifacts.
    '''

    def __init__(self, external_repository_data, repository_handle):
        self.external_repository_data = check.inst_param(
            external_repository_data, 'external_repository_data', ExternalRepositoryData
        )
        self._pipeline_index_map = OrderedDict(
            (
                external_pipeline_data.pipeline_snapshot.name,
                PipelineIndex(
                    external_pipeline_data.pipeline_snapshot,
                    external_pipeline_data.parent_pipeline_snapshot,
                ),
            )
            for external_pipeline_data in external_repository_data.external_pipeline_datas
        )
        self._handle = check.inst_param(repository_handle, 'repository_handle', RepositoryHandle)

    @property
    def name(self):
        return self.external_repository_data.name

    def get_pipeline_index(self, pipeline_name):
        return self._pipeline_index_map[pipeline_name]

    def has_pipeline(self, pipeline_name):
        return pipeline_name in self._pipeline_index_map

    def get_pipeline_indices(self):
        return self._pipeline_index_map.values()

    def has_external_pipeline(self, pipeline_name):
        return pipeline_name in self._pipeline_index_map

    def get_full_external_pipeline(self, pipeline_name):
        check.str_param(pipeline_name, 'pipeline_name')
        return ExternalPipeline(
            self.external_repository_data.get_external_pipeline_data(pipeline_name),
            repository_handle=self.handle,
        )

    def get_all_external_pipelines(self):
        return [self.get_full_external_pipeline(pn) for pn in self._pipeline_index_map]

    @property
    def handle(self):
        return self._handle


class ExternalPipeline(RepresentedPipeline):
    '''
    ExternalPipeline is a object that represents a loaded pipeline definition that
    is resident in another process or container. Host processes such as dagit use
    objects such as these to interact with user-defined artifacts.
    '''

    def __init__(self, external_pipeline_data, repository_handle):
        check.inst_param(repository_handle, 'repository_handle', RepositoryHandle)
        check.inst_param(external_pipeline_data, 'external_pipeline_data', ExternalPipelineData)

        super(ExternalPipeline, self).__init__(
            pipeline_index=PipelineIndex(
                external_pipeline_data.pipeline_snapshot,
                external_pipeline_data.parent_pipeline_snapshot,
            )
        )
        self._active_preset_dict = {ap.name: ap for ap in external_pipeline_data.active_presets}
        self._handle = PipelineHandle(self._pipeline_index.name, repository_handle)

    @property
    def solid_subset(self):
        return (
            self._pipeline_index.pipeline_snapshot.lineage_snapshot.solid_subset
            if self._pipeline_index.pipeline_snapshot.lineage_snapshot
            else None
        )

    @property
    def active_presets(self):
        return list(self._active_preset_dict.values())

    @property
    def solid_names(self):
        return self._pipeline_index.pipeline_snapshot.solid_names

    def has_solid_invocation(self, solid_name):
        check.str_param(solid_name, 'solid_name')
        return self._pipeline_index.has_solid_invocation(solid_name)

    def has_preset(self, preset_name):
        check.str_param(preset_name, 'preset_name')
        return preset_name in self._active_preset_dict

    def get_preset(self, preset_name):
        check.str_param(preset_name, 'preset_name')
        return self._active_preset_dict[preset_name]

    def has_mode(self, mode_name):
        check.str_param(mode_name, 'mode_name')
        return self._pipeline_index.has_mode_def(mode_name)

    def root_config_key_for_mode(self, mode_name):
        check.opt_str_param(mode_name, 'mode_name')
        return self.get_mode_def_snap(
            mode_name if mode_name else self.get_default_mode_name()
        ).root_config_key

    def get_default_mode_name(self):
        return self._pipeline_index.get_default_mode_name()

    @property
    def tags(self):
        return self._pipeline_index.pipeline_snapshot.tags

    @property
    def computed_pipeline_snapshot_id(self):
        return self._pipeline_index.pipeline_snapshot_id

    @property
    def identifying_pipeline_snapshot_id(self):
        return self._pipeline_index.pipeline_snapshot_id

    @property
    def handle(self):
        return self._handle


class ExternalExecutionPlan:
    '''
    ExternalExecution is a object that represents an execution plan that
    was compiled in another process or persisted in an instance.
    '''

    def __init__(self, execution_plan_snapshot, represented_pipeline):
        self.execution_plan_snapshot = check.inst_param(
            execution_plan_snapshot, 'execution_plan_snapshot', ExecutionPlanSnapshot
        )
        self.represented_pipeline = check.inst_param(
            represented_pipeline, 'represented_pipeline', RepresentedPipeline
        )

        self._step_index = {step.key: step for step in self.execution_plan_snapshot.steps}

        check.invariant(
            execution_plan_snapshot.pipeline_snapshot_id
            == represented_pipeline.identifying_pipeline_snapshot_id
        )

        self._step_keys_in_plan = (
            set(execution_plan_snapshot.step_keys_to_execute)
            if execution_plan_snapshot.step_keys_to_execute
            else set(self._step_index.keys())
        )

        self._deps = None
        self._topological_steps = None
        self._topological_step_levels = None

    @property
    def step_keys_in_plan(self):
        return list(self._step_keys_in_plan)

    def has_step(self, key):
        check.str_param(key, 'key')
        return key in self._step_index

    def get_step_by_key(self, key):
        check.str_param(key, 'key')
        return self._step_index[key]

    def get_steps_in_plan(self):
        return [self._step_index[sk] for sk in self._step_keys_in_plan]

    def key_in_plan(self, key):
        return key in self._step_keys_in_plan

    # Everything below this line is a near-copy of the equivalent methods on
    # ExecutionPlan. We should resolve this, probably eventually by using the
    # snapshots to support the existing ExecutionPlan methods.
    # https://github.com/dagster-io/dagster/issues/2462
    def execution_deps(self):
        if self._deps is None:
            deps = OrderedDict()

            for key in self._step_keys_in_plan:
                deps[key] = set()

            for key in self._step_keys_in_plan:
                step = self._step_index[key]
                for step_input in step.inputs:
                    deps[step.key].update(
                        {
                            output_handle.step_key
                            for output_handle in step_input.upstream_output_handles
                        }.intersection(self._step_keys_in_plan)
                    )
            self._deps = deps

        return self._deps

    def topological_steps(self):
        if self._topological_steps is None:
            self._topological_steps = [
                step for step_level in self.topological_step_levels() for step in step_level
            ]

        return self._topological_steps

    def topological_step_levels(self):
        if self._topological_step_levels is None:
            self._topological_step_levels = [
                [self._step_index[step_key] for step_key in sorted(step_key_level)]
                for step_key_level in toposort(self.execution_deps())
            ]

        return self._topological_step_levels
