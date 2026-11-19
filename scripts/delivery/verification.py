"""Provenance for a runtime report produced by a trusted verification job."""
import io
import json
import os
import subprocess
import zipfile

from common import Rejected


def api(path, binary=False):
    env = os.environ.copy()
    if env.get("REPORT_READ_TOKEN"):
        env["GH_TOKEN"] = env["REPORT_READ_TOKEN"]
    result = subprocess.run(["gh", "api", path], check=True, capture_output=True, env=env)
    return result.stdout if binary else json.loads(result.stdout)


def items(path, collection):
    page = 1
    while True:
        batch = api(f"{path}?per_page=100&page={page}")[collection]
        yield from batch
        if len(batch) < 100:
            return
        page += 1


def producer_job(environment):
    return f"verify ({environment})"


def require_pass(report, application, environment):
    if (type(report.get("schema_version")) is not int or report["schema_version"] != 1
            or report.get("result") != "passed" or report.get("verified") is not True
            or report.get("application_id") != application or report.get("environment") != environment
            or report.get("producer_job") != producer_job(environment)):
        raise Rejected("A current passing source report is required; reverify the source environment")
    image = report["release"]["image"]
    observed = report["observed"]
    pod_images = observed.get("pod_image_ids")
    if (not isinstance(pod_images, list) or not pod_images
            or not all(isinstance(value, str) and image["digest"] in value for value in pod_images)
            or observed.get("gitops_revision") != report["config_revision"]
            or observed.get("image") != f"{image['repository']}@{image['digest']}"
            or observed.get("source_commit") != report["release"]["delivery"]["sourceCommit"]):
        raise Rejected("Observed workload does not match the accepted release")


def require_source_job(specific, job_name, attempt, revision):
    jobs = [job for job in items(f"{specific}/jobs", "jobs") if job["name"] == job_name]
    if (len(jobs) != 1 or jobs[0].get("conclusion") != "success"
            or str(jobs[0].get("run_attempt", attempt)) != attempt or jobs[0].get("head_sha") != revision):
        raise Rejected(f"Successful source job required: {job_name} (attempt {attempt})")


def verified_report(repository, run_id, attempt, source):
    if not run_id.isdecimal() or not attempt.isdecimal() or source not in ("aws-dev", "aws-test"):
        raise Rejected("Invalid verification workflow identity")
    path = f"repos/{repository}/actions/runs/{run_id}"
    specific = f"{path}/attempts/{attempt}"
    workflow = api(specific)
    callers = {".github/workflows/delivery-runtime.yaml": f"verify-{source.removeprefix('aws-')}",
               ".github/workflows/delivery-promote.yaml": "verify-source"}
    caller = callers.get(workflow.get("path"))
    if (not caller or workflow.get("head_branch") != "main"
            or workflow.get("head_repository", {}).get("full_name", "").lower() != repository.lower()
            or str(workflow.get("id")) != run_id or str(workflow.get("run_attempt")) != attempt
            or workflow.get("event") not in ("push", "workflow_dispatch")):
        raise Rejected("Verification must come from a trusted main workflow attempt")
    job_name = f"{caller} / {producer_job(source)}"
    require_source_job(specific, job_name, attempt, workflow["head_sha"])
    name = f"delivery-verified-{source}-{run_id}-{attempt}"
    report = read_artifact(repository, path, name, "verified.json")
    if (report.get("config_revision") != workflow["head_sha"] or report.get("repository") != repository
            or report.get("run_id") != run_id or report.get("run_attempt") != attempt
            or report.get("environment") != source or report.get("producer_job") != producer_job(source)):
        raise Rejected("Report identity differs from its trusted source job")
    return report


def read_artifact(repository, path, name, filename):
    selected = [item for item in items(path + "/artifacts", "artifacts")
                if item["name"] == name and not item["expired"]]
    if len(selected) != 1:
        raise Rejected("Required artifact missing or expired: " + name)
    item = selected[0]
    if item["size_in_bytes"] > 1024 * 1024:
        raise Rejected("Unexpected verification artifact size")
    archive = api(f"repos/{repository}/actions/artifacts/{item['id']}/zip", binary=True)
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        if zipped.namelist() != [filename] or zipped.getinfo(filename).file_size > 65536:
            raise Rejected("Unexpected verification artifact contents")
        return json.loads(zipped.read(filename))
