import * as React from "react";
import gql from "graphql-tag";
import { useQuery } from "react-apollo";
import { RouteComponentProps } from "react-router-dom";
import styled from "styled-components/macro";
import { Colors, NonIdealState, Icon, Tooltip } from "@blueprintjs/core";
import PipelineGraph from "../graph/PipelineGraph";
import { IconNames } from "@blueprintjs/icons";
import Loading from "../Loading";
import {
  PipelineOverviewQuery,
  PipelineOverviewQuery_pipelineSnapshotOrError_PipelineSnapshot_runs,
  PipelineOverviewQuery_pipelineSnapshotOrError_PipelineSnapshot_schedules,
  PipelineOverviewQueryVariables
} from "./types/PipelineOverviewQuery";
import { RowColumn, RowContainer } from "../ListComponents";
import { RunStatus, titleForRun } from "../runs/RunUtils";
import { Link } from "react-router-dom";
import { unixTimestampToString } from "../Util";
import {
  RunActionsMenu,
  TimeElapsed,
  RunStatsDetails,
  RunComponentFragments
} from "../runs/RunUtils";
import { getDagrePipelineLayout } from "../graph/getFullSolidLayout";
import SVGViewport from "../graph/SVGViewport";
import { RUNS_ROOT_QUERY, RunsQueryVariablesContext } from "../runs/RunsRoot";

type Run = PipelineOverviewQuery_pipelineSnapshotOrError_PipelineSnapshot_runs;
type Schedule = PipelineOverviewQuery_pipelineSnapshotOrError_PipelineSnapshot_schedules;

export const PipelineOverviewRoot: React.FunctionComponent<RouteComponentProps<{
  pipelinePath: string;
}>> = ({ match }) => {
  const pipelineName = match.params.pipelinePath.split(":")[0];

  const queryResult = useQuery<
    PipelineOverviewQuery,
    PipelineOverviewQueryVariables
  >(PIPELINE_OVERVIEW_QUERY, {
    fetchPolicy: "cache-and-network",
    partialRefetch: true,
    variables: { pipelineName, limit: 5 }
  });
  return (
    <Loading queryResult={queryResult}>
      {({ pipelineSnapshotOrError }) => {
        if (
          pipelineSnapshotOrError.__typename === "PipelineSnapshotNotFoundError"
        ) {
          return (
            <NonIdealState
              icon={IconNames.FLOW_BRANCH}
              title="Pipeline Snapshot Not Found"
              description={pipelineSnapshotOrError.message}
            />
          );
        }
        if (pipelineSnapshotOrError.__typename === "PipelineNotFoundError") {
          return (
            <NonIdealState
              icon={IconNames.FLOW_BRANCH}
              title="Pipeline Not Found"
              description={pipelineSnapshotOrError.message}
            />
          );
        }
        if (pipelineSnapshotOrError.__typename === "PythonError") {
          return (
            <NonIdealState
              icon={IconNames.ERROR}
              title="Query Error"
              description={pipelineSnapshotOrError.message}
            />
          );
        }

        const solids = pipelineSnapshotOrError.solidHandles.map(
          handle => handle.solid
        );
        const schedules = pipelineSnapshotOrError.schedules;

        return (
          <RootContainer>
            <MainContainer>
              <OverviewSection title="Definition">
                <div
                  style={{
                    position: "relative",
                    height: 550,
                    maxWidth: "40vw",
                    border: "1px solid #ececec"
                  }}
                >
                  <PipelineGraph
                    pipelineName={pipelineName}
                    backgroundColor={Colors.LIGHT_GRAY5}
                    solids={solids}
                    layout={getDagrePipelineLayout(solids)}
                    interactor={SVGViewport.Interactors.None}
                    focusSolids={[]}
                    highlightedSolids={[]}
                  />
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "flex-end",
                      margin: "10px 0"
                    }}
                  >
                    <Link to={`/pipeline/${pipelineName}:`}>
                      Explore Pipeline Definition &gt;
                    </Link>
                  </div>
                </div>
              </OverviewSection>
              <OverviewSection title="Description">
                {pipelineSnapshotOrError.description ||
                  "No description provided"}
              </OverviewSection>
            </MainContainer>
            <SecondaryContainer>
              <OverviewSection title="Schedule">
                {schedules.length
                  ? schedules.map(schedule => (
                      <OverviewSchedule
                        schedule={schedule}
                        key={schedule.scheduleDefinition.name}
                      />
                    ))
                  : "No pipeline schedules"}
              </OverviewSection>
              <OverviewSection title="Recent runs">
                {pipelineSnapshotOrError.runs.length
                  ? pipelineSnapshotOrError.runs.map(run => (
                      <OverviewRun run={run} key={run.runId} />
                    ))
                  : "No recent runs"}
              </OverviewSection>
            </SecondaryContainer>
            <SecondaryContainer>
              <OverviewAssets runs={pipelineSnapshotOrError.runs} />
            </SecondaryContainer>
          </RootContainer>
        );
      }}
    </Loading>
  );
};

const OverviewAssets = ({ runs }: { runs: Run[] }) => {
  const assetMap = {};
  runs.forEach(run => {
    run.assets.forEach(asset => {
      assetMap[asset.key] = true;
    });
  });
  const assetKeys = Object.keys(assetMap);
  return (
    <OverviewSection title="Related assets">
      {assetKeys.length
        ? assetKeys.map(assetKey => (
            <RowContainer
              key={assetKey}
              style={{ padding: 10, paddingBottom: 30 }}
            >
              <Link to={`/assets/${assetKey}`}>{assetKey}</Link>
            </RowContainer>
          ))
        : "No recent assets"}
    </OverviewSection>
  );
};

const OverviewSchedule = ({ schedule }: { schedule: Schedule }) => {
  const lastRun = schedule.runs.length && schedule.runs[0];
  return (
    <RowContainer style={{ paddingRight: 3 }}>
      <RowColumn>
        <Link to={`/schedules/${schedule.scheduleDefinition.name}`}>
          {schedule.scheduleDefinition.name}
        </Link>
        {lastRun && lastRun.stats.__typename === "PipelineRunStatsSnapshot" ? (
          <div style={{ color: Colors.GRAY3, fontSize: 12, marginTop: 2 }}>
            Last Run: {unixTimestampToString(lastRun.stats.endTime)}
          </div>
        ) : null}
        <div style={{ marginTop: 5 }}>
          {schedule.runs.map(run => {
            return (
              <div
                style={{
                  display: "inline-block",
                  cursor: "pointer",
                  marginRight: 5
                }}
                key={run.runId}
              >
                <Link to={`/runs/${run.pipeline.name}/${run.runId}`}>
                  <Tooltip
                    position={"top"}
                    content={titleForRun(run)}
                    wrapperTagName="div"
                    targetTagName="div"
                  >
                    <RunStatus status={run.status} />
                  </Tooltip>
                </Link>
              </div>
            );
          })}
        </div>
      </RowColumn>
    </RowContainer>
  );
};

const OverviewRun = ({ run }: { run: Run }) => {
  const variables = React.useContext(RunsQueryVariablesContext);
  const time =
    run.stats.__typename === "PipelineRunStatsSnapshot" ? (
      <>
        {run.stats.startTime ? (
          <div style={{ marginBottom: 4 }}>
            <Icon icon="calendar" />{" "}
            {unixTimestampToString(run.stats.startTime)}
            <Icon
              icon="arrow-right"
              style={{ marginLeft: 10, marginRight: 10 }}
            />
            {unixTimestampToString(run.stats.endTime)}
          </div>
        ) : run.status === "FAILURE" ? (
          <div style={{ marginBottom: 4 }}> Failed to start</div>
        ) : (
          <div style={{ marginBottom: 4 }}>
            <Icon icon="calendar" /> Starting...
          </div>
        )}
        <TimeElapsed
          startUnix={run.stats.startTime}
          endUnix={run.stats.endTime}
        />
      </>
    ) : null;

  const refetchQueries = [{ query: RUNS_ROOT_QUERY, variables }];

  return (
    <RowContainer style={{ paddingRight: 3 }}>
      <RowColumn style={{ maxWidth: 30, paddingLeft: 0, textAlign: "center" }}>
        <RunStatus status={run.status} />
      </RowColumn>
      <RowColumn style={{ flex: 2.4 }}>
        <Link to={`/runs/${run.pipeline.name}/${run.runId}`}>
          {titleForRun(run)}
        </Link>
        <RunStatsDetails run={run} />
        <div style={{ margin: "5px 0" }}>{`Mode: ${run.mode}`}</div>
        {time}
      </RowColumn>
      <RowColumn style={{ maxWidth: 50 }}>
        <RunActionsMenu run={run} refetchQueries={refetchQueries} />
      </RowColumn>
    </RowContainer>
  );
};

const OverviewSection = ({
  title,
  children
}: {
  title: string;
  children: any;
}) => {
  return (
    <div style={{ marginBottom: 50 }}>
      <div
        style={{
          textTransform: "uppercase",
          color: Colors.GRAY2,
          marginBottom: 10
        }}
      >
        {title}
      </div>
      {children}
    </div>
  );
};

const RootContainer = styled.div`
  flex: 1;
  display: flex;
`;
const MainContainer = styled.div`
  flex: 2;
  max-width: 1200px;
  padding: 20px;
`;
const SecondaryContainer = ({ children }: { children: React.ReactNode }) => (
  <div style={{ maxWidth: 600, padding: 20, flex: 1 }}>
    <div style={{ maxWidth: "25vw" }}>{children}</div>
  </div>
);

const ScheduleFragment = gql`
  fragment OverviewScheduleFragment on RunningSchedule {
    __typename
    scheduleDefinition {
      name
      cronSchedule
      pipelineName
      solidSubset
      mode
      runConfigYaml
    }
    ticks(limit: 1) {
      tickId
      status
    }
    runsCount
    runs(limit: 10) {
      runId
      pipeline {
        name
      }
      stats {
        ... on PipelineRunStatsSnapshot {
          endTime
        }
      }
      status
    }
    stats {
      ticksStarted
      ticksSucceeded
      ticksSkipped
      ticksFailed
    }
    ticksCount
    status
  }
`;

export const PIPELINE_OVERVIEW_QUERY = gql`
  query PipelineOverviewQuery($pipelineName: String, $limit: Int!) {
    pipelineSnapshotOrError(activePipelineName: $pipelineName) {
      ... on PipelineSnapshot {
        name
        description
        solidHandles(parentHandleID: "") {
          solid {
            name
            ...PipelineGraphSolidFragment
          }
        }
        runs(limit: $limit) {
          ...RunActionMenuFragment
          ...RunStatsDetailFragment
          ...RunTimeFragment
          assets {
            key
          }
        }
        schedules {
          ...OverviewScheduleFragment
        }
      }
      ... on PipelineNotFoundError {
        message
      }
      ... on PipelineSnapshotNotFoundError {
        message
      }
      ... on PythonError {
        message
      }
    }
  }
  ${PipelineGraph.fragments.PipelineGraphSolidFragment}
  ${ScheduleFragment}
  ${RunComponentFragments.STATS_DETAIL_FRAGMENT}
  ${RunComponentFragments.RUN_TIME_FRAGMENT}
  ${RunComponentFragments.RUN_ACTION_MENU_FRAGMENT}
`;
