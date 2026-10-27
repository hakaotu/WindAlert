/**
 * WindAlert pinger: starts the "Wind alert check" workflow every 5 minutes.
 *
 * GitHub's own cron is best-effort and in practice runs a few times a day, so
 * this Apps Script timer calls the workflow_dispatch API instead. The GitHub
 * cron stays in run_alert.yml as a fallback. Setup: docs/hosting-github-actions.md
 *
 * Script Properties (Project Settings -> Script Properties):
 *   GITHUB_TOKEN  fine-grained personal access token, only this repository,
 *                 only the permission "Actions: Read and write"
 *   GITHUB_REPO   owner/name, for example hakaotu/WindAlert
 *
 * Run installTrigger once to start; removeTrigger switches the pinger off.
 */

const WORKFLOW_FILE = 'run_alert.yml';
const TZ = 'Europe/Helsinki';
// Must cover schedule.active_hours in config.yaml. Covering more is safe: the
// Python window check decides whether a run does anything.
const START_HOUR = 6;
const END_HOUR = 22;

function ping() {
  const h = Number(Utilities.formatDate(new Date(), TZ, 'H'));
  if (h < START_HOUR || h >= END_HOUR) {
    console.log('Outside pinger hours - no dispatch');
    return;
  }

  const props = PropertiesService.getScriptProperties();
  const token = props.getProperty('GITHUB_TOKEN');
  const repo = props.getProperty('GITHUB_REPO');
  if (!token) throw new Error('Script Property GITHUB_TOKEN is missing');
  if (!repo) throw new Error('Script Property GITHUB_REPO is missing');

  const url = 'https://api.github.com/repos/' + repo + '/actions/workflows/' + WORKFLOW_FILE + '/dispatches';
  const response = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    muteHttpExceptions: true,
    headers: {
      Authorization: 'Bearer ' + token,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    payload: JSON.stringify({ ref: 'main', inputs: { trigger: 'pinger' } }),
  });
  const code = response.getResponseCode();
  if (code < 200 || code >= 300) {
    throw new Error('GitHub dispatch failed: HTTP ' + code + ' ' + response.getContentText().slice(0, 300));
  }
  console.log('Dispatched (HTTP ' + code + ')');
}

function removeTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'ping') ScriptApp.deleteTrigger(t);
  });
}

function installTrigger() {
  removeTrigger();  // so running this twice cannot double the rate
  ScriptApp.newTrigger('ping').timeBased().everyMinutes(5).create();
  console.log('Trigger installed: ping every 5 min');
  ping();
}
