import http from "k6/http";
import { check } from "k6";


http.setResponseCallback(http.expectedStatuses({ min: 200, max: 399 }, 404));


const analyzerUrl = __ENV.ANALYZER_URL || "http://host.docker.internal:8082";
const cleanerUrl = __ENV.CLEANER_URL || "http://host.docker.internal:8081";
const serviceToken = __ENV.INTERNAL_API_TOKEN || "local-development-token";


export const options = {
  scenarios: {
    completedReportReads: {
      executor: "constant-vus",
      vus: Number(__ENV.VUS || 20),
      duration: __ENV.DURATION || "10s",
      exec: "completedReportReads",
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<250", "p(99)<500"],
  },
};


const authenticatedHeaders = {
  headers: {
    "X-Service-Token": serviceToken,
  },
};


export function completedReportReads() {
  const responses = http.batch([
    ["GET", `${analyzerUrl}/health/ready`],
    ["GET", `${cleanerUrl}/health/ready`],
    [
      "GET",
      `${analyzerUrl}/manager/dialogs/load-test-missing`,
      null,
      authenticatedHeaders,
    ],
    [
      "GET",
      `${analyzerUrl}/manager/00000001/dialogs?date=2026-10-22`,
      null,
      authenticatedHeaders,
    ],
  ]);

  check(responses[0], {
    "analyzer is ready": (response) => response.status === 200,
  });
  check(responses[1], {
    "cleaner is ready": (response) => response.status === 200,
  });
  check(responses[2], {
    "unfinished dialog is hidden": (response) => response.status === 404,
  });
  check(responses[3], {
    "unfinished daily report is hidden": (response) => response.status === 404,
  });
}
