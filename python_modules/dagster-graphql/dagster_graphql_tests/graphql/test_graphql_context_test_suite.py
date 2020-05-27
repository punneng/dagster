import inspect
import sys

import pytest
from dagster_graphql.test.exploding_run_launcher import ExplodingRunLauncher

from dagster import check

from .graphql_context_test_suite import (
    MARK_MAP,
    GraphQLContextVariant,
    GraphQLTestEnvironments,
    GraphQLTestExecutionManagers,
    GraphQLTestInstances,
    manage_graphql_context,
)


@pytest.mark.parametrize('variant', GraphQLContextVariant.all_readonly_variants())
def test_readonly_variants(variant):
    assert isinstance(variant, GraphQLContextVariant)
    with manage_graphql_context(variant) as context:
        assert context.legacy_environment.execution_manager is None
        assert isinstance(context.instance.run_launcher, ExplodingRunLauncher)


@pytest.mark.parametrize('variant', GraphQLContextVariant.all_hijacking_launcher_variants())
def test_hijacking_variants(variant):
    assert isinstance(variant, GraphQLContextVariant)
    assert pytest.mark.hijacking in variant.marks
    with manage_graphql_context(variant) as context:
        assert context.legacy_environment.execution_manager is None
        assert context.instance.run_launcher.hijack_start


@pytest.mark.parametrize(
    'variant', GraphQLContextVariant.all_variants_with_legacy_execution_manager()
)
def test_legacy_variants(variant):
    assert isinstance(variant, GraphQLContextVariant)
    with manage_graphql_context(variant) as context:
        assert context.legacy_environment.execution_manager


def get_all_static_functions_on_fixture_classes():
    def _yield_all():
        for klass in [GraphQLTestInstances, GraphQLTestEnvironments, GraphQLTestExecutionManagers]:
            for static_function in get_all_static_functions(klass):
                yield static_function

    return list(_yield_all())


def get_all_static_functions(klass):
    check.invariant(sys.version_info >= (3,))

    def _yield_all():
        for attr_name in dir(klass):
            attr = inspect.getattr_static(klass, attr_name)
            if isinstance(attr, staticmethod):
                # the actual function is on the __func__ property
                yield attr.__func__

    return list(_yield_all())


@pytest.mark.skipif(sys.version_info < (3,), reason="This behavior isn't available on 2.7")
def test_get_all_static_members():
    class Bar:
        class_var = 'foo'

        @staticmethod
        def static_one():
            pass

        @staticmethod
        def static_two():
            pass

        @classmethod
        def classthing(cls):
            pass

    assert set(get_all_static_functions(Bar)) == {Bar.static_one, Bar.static_two}


@pytest.mark.skipif(sys.version_info < (3,), reason="This behavior isn't available on 2.7")
@pytest.mark.parametrize(
    'static_function',
    get_all_static_functions_on_fixture_classes() if sys.version_info > (3,) else [],
)
def test_mark_map_is_fully_populated(static_function):
    assert static_function in MARK_MAP, (
        'All static functions on GraphQLTestInstances, GraphQLTestEnvironments, '
        'and GraphQLTestExecutionManagers must be registered in the MARK_MAP. This '
        'ensures that the GraphQLContextVariants end up being properly categorized. '
        'In this case {static_function} must be placed in the MARK_MAP.'
    ).format(static_function=static_function)


@pytest.mark.skipif(sys.version_info < (3,), reason="This behavior isn't available on 2.7")
def test_all_variants_in_variants_function():
    '''
    This grabs all pre-defined variants on GraphQLContextVariant (defined as static methods that
    return a single ContextVariant) and tests two things:
    1) They all contain a unique test_id
    2) That the all_variants() static method returns *all* of them
    '''

    variant_test_ids_declared_on_class = set()
    for static_function in get_all_static_functions(GraphQLContextVariant):
        maybe_variant = static_function()
        if isinstance(maybe_variant, GraphQLContextVariant):
            assert maybe_variant.test_id
            assert maybe_variant.test_id not in variant_test_ids_declared_on_class
            variant_test_ids_declared_on_class.add(maybe_variant.test_id)

    test_ids_returned_by_all_variants = {
        var.test_id for var in GraphQLContextVariant.all_variants()
    }

    assert test_ids_returned_by_all_variants == variant_test_ids_declared_on_class


def test_readonly_marks_filter():
    readonly_test_ids = {
        var.test_id
        for var in [
            GraphQLContextVariant.readonly_in_memory_instance_in_process_env(),
            GraphQLContextVariant.readonly_in_memory_instance_out_of_process_env(),
            GraphQLContextVariant.readonly_sqlite_instance_in_process_env(),
            GraphQLContextVariant.readonly_sqlite_instance_out_of_process_env(),
        ]
    }

    assert {
        var.test_id for var in GraphQLContextVariant.all_readonly_variants()
    } == readonly_test_ids


def test_legacy_execution_manager_marks_filter():
    legacy_test_ids = {
        var.test_id
        for var in [
            GraphQLContextVariant.sqlite_in_process_start(),
            GraphQLContextVariant.sqlite_subprocess_start(),
            GraphQLContextVariant.in_memory_in_process_start(),
        ]
    }

    assert {
        var.test_id for var in GraphQLContextVariant.all_variants_with_legacy_execution_manager()
    } == legacy_test_ids


def test_hijacking_marks_filter():
    hijacking_test_ids = {
        var.test_id
        for var in [
            GraphQLContextVariant.in_memory_instance_with_sync_hijack(),
            GraphQLContextVariant.sqlite_with_cli_api_hijack(),
            GraphQLContextVariant.sqlite_with_sync_hijack(),
        ]
    }

    assert {
        var.test_id for var in GraphQLContextVariant.all_hijacking_launcher_variants()
    } == hijacking_test_ids