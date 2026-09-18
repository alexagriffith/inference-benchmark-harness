"""Bounded mixed-matrix qualification against two localhost HTTP fixtures.

Requires installed AIPerf; retains exact commands, evidence and a compact result.
No external endpoint or cluster is contacted by this test.
"""

import argparse
import copy
import hashlib
from http.server import ThreadingHTTPServer
import json
import math
import os
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

from integration import Handler

ROOT = Path(__file__).resolve().parents[1]


class InteractiveHandler(Handler):
    requests = []
    failures = False


class BackgroundHandler(Handler):
    requests = []
    failures = False
    failure_peer_baseline = 0

    def do_POST(self):
        if self.failures:
            # Ensure the peer has real traffic to preserve, without indefinite wait.
            until = time.monotonic() + 2
            while len(InteractiveHandler.requests) <= self.failure_peer_baseline and time.monotonic() < until:
                time.sleep(0.01)
        super().do_POST()


def read(path):
    return json.loads(path.read_text())


def digests(directory):
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob('*') if p.is_file()}


def validate_group(directory, minimum):
    summary = read(directory / 'summary.json')
    assert summary['evidence'] == 'complete', summary
    assert summary['outcome'] == 'ready', summary
    rows = {name: [json.loads(line) for line in
                   (directory / name / 'native/profile_export.jsonl').read_text().splitlines() if line.strip()]
            for name in ('interactive', 'background')}
    starts = {name: [row['metadata']['request_start_ns'] for row in values] for name, values in rows.items()}
    begin = max(min(values) for values in starts.values())
    end = min(max(values) for values in starts.values())
    overlap = summary['overlap']
    assert overlap['basis'] == 'observed_request_arrivals', overlap
    assert (overlap['start_ns'], overlap['end_ns']) == (begin, end), overlap
    assert overlap['seconds'] == (end-begin)/1e9 >= minimum, overlap
    assert overlap['valid'], overlap
    for name, values in rows.items():
        cohort = [row for row in values if begin <= row['metadata']['request_start_ns'] <= end]
        assert len(cohort) == overlap['arrivals_in_common_window'][name] > 0, overlap
        assert overlap['window_covered'][name]
        shared = summary['shared_window'][name]
        assert shared['basis'] == 'request_start_ns_in_inclusive_common_arrival_window', shared
        assert shared['requests'] == len(cohort) and shared['failed_requests'] == 0, shared
        assert shared['percentile_method'] == 'nearest_rank' and shared['goals'] == [], shared
        for metric, field in (('request_latency','latency_p95_ms'), ('time_to_first_token','ttft_p95_ms')):
            measured = sorted(row['metrics'][metric]['value'] for row in cohort)
            assert all(row['metrics'][metric]['unit'] == 'ms' for row in cohort)
            assert shared['sample_counts'][field]['valid'] == len(cohort), shared
            assert shared['measurements'][field] == measured[math.ceil(.95*len(measured))-1], shared
        assert 0 < len(values) <= 6, len(values)
        native = read(directory / name / 'summary.json')
        assert native['evidence'] == 'complete' and native['failed_requests'] == 0, native
        assert native['requests'] == len(values), native
        assert (directory / name / 'manifest.json').is_file()
    return {'directory': directory.name, 'overlap_seconds': overlap['seconds'],
            'start_skew_seconds': overlap['start_skew_seconds'],
            'arrivals_in_common_window': overlap['arrivals_in_common_window'],
            'requests': {name: len(values) for name, values in rows.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--aiperf', required=True)
    parser.add_argument('--output', type=Path, help='New directory for preserved qualification artifacts')
    args = parser.parse_args()
    output = args.output.resolve() if args.output else Path(tempfile.mkdtemp(prefix='inference-matrix-integration-'))
    if args.output:
        output.mkdir(parents=True, exist_ok=False)
    env = {**os.environ, 'FIXTURE_API_KEY':'fixture-key', 'PYTHONDONTWRITEBYTECODE':'1'}
    servers, threads, commands = [], [], []
    for fixture in (InteractiveHandler, BackgroundHandler):
        fixture.requests = []
        fixture.failures = False
        server = ThreadingHTTPServer(('127.0.0.1',0),fixture)
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start(); servers.append(server); threads.append(thread)
    print(json.dumps({'artifacts':str(output),'maximum_requests':96}),flush=True)

    def run(case, action, config_path, directory, resume=False):
        argv = [sys.executable,'-m','bench',action,'--config',str(config_path),'--run',str(directory),'--aiperf',args.aiperf]
        if action == 'matrix-run':
            argv.append('--execute')
        if resume:
            argv.append('--resume')
        source_hashes = {str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in sorted((ROOT/'bench').glob('*.py'))}
        process = subprocess.Popen(argv,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                   text=True,start_new_session=True)
        termination = {'timed_out':False,'pid':process.pid}
        try:
            stdout,stderr = process.communicate(timeout=300)
        except subprocess.TimeoutExpired:
            termination.update(timed_out=True,action='SIGTERM_parent',grace_seconds=15)
            # Let the CLI checkpoint its interruption and clean its owned AIPerf groups.
            try:
                process.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                stdout,stderr = process.communicate(timeout=15)
                termination['graceful_exit_observed'] = True
            except subprocess.TimeoutExpired:
                termination.update(action='SIGKILL_parent_group',graceful_exit_observed=False,
                                   child_cleanup='unconfirmed; inspect preserved execution evidence')
                try:
                    os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:
                    pass
                stdout,stderr = process.communicate()
        completed = subprocess.CompletedProcess(argv,process.returncode,stdout,stderr)
        commands.append({'case':case,'argv':argv,'exit_code':completed.returncode,'source_sha256':source_hashes,
                         'termination':termination,'stdout':completed.stdout,'stderr':completed.stderr})
        (output/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        print(json.dumps({'case':case,'exit_code':completed.returncode}),flush=True)
        if termination['timed_out']:
            raise TimeoutError(f'{case} exceeded 300 seconds; termination and output saved in commands.json')
        return completed

    try:
        for name,server in zip(('a','b'),servers):
            config = read(ROOT/'examples/benchmark.json')
            config['endpoint'].update(url=f'http://127.0.0.1:{server.server_port}',model='fixture-model',api_key_env='FIXTURE_API_KEY')
            config['load'].update(concurrency=[1],repeats=1,requests=6,duration_seconds=4,
                                  request_timeout_seconds=2,grace_seconds=1,deadline_seconds=30)
            config['goals'] = {}
            config['metrics'] = [{'name':'fixture','url':config['endpoint']['url']+'/metrics',
                                  'required':[{'metric':'fixture_requests_total','why':'Verify collection across local mixed traffic'}]}]
            (output/f'{name}.json').write_text(json.dumps(config,indent=2)+'\n')
        matrix = {'schema_version':1,'name':'fixture-mix','repeats':3,'max_attempts_per_repeat':3,
                  'min_overlap_seconds':0.1,'stages':[{'id':'mix','question':'Do both fixture workloads overlap?',
                  'change':'Hold interactive rate while increasing background rate.',
                  'streams':{'interactive':{'config':'a.json','load':{'rates':[2],'arrival':'constant','max_concurrency':2}},
                             'background':{'config':'b.json','load':{'rates':[1,2],'arrival':'constant','max_concurrency':2}}}}]}
        matrix_path = output/'matrix.json';matrix_path.write_text(json.dumps(matrix,indent=2)+'\n')
        campaign = output/'sweep'
        result = run('plan','matrix-plan',matrix_path,campaign)
        assert result.returncode == 0, result.stdout+result.stderr
        plan = json.loads(result.stdout)
        assert plan['rows'] == 2 and plan['repeats_per_row'] == 3, plan
        assert plan['max_requests_first_pass'] == 72 and plan['automatic_inference_retries'] == 0, plan
        assert not campaign.exists(), 'Plan created execution artifacts'
        assert not InteractiveHandler.requests and not BackgroundHandler.requests, 'Plan sent traffic'
        result = run('mixed-sweep','matrix-run',matrix_path,campaign)
        assert result.returncode == 0, result.stdout+result.stderr
        state = read(campaign/'state.json')
        assert state['status'] == 'complete' and len(state['completed']) == 6, state
        groups = [validate_group(campaign/name,matrix['min_overlap_seconds']) for name in state['completed']]
        sweep_requests = sum(len(fixture.requests) for fixture in (InteractiveHandler,BackgroundHandler))
        assert 0 < sweep_requests <= 72, sweep_requests
        saved = {name:digests(campaign/name) for name in state['completed']}
        result = run('completed-resume','matrix-run',matrix_path,campaign,resume=True)
        assert result.returncode == 0, result.stdout+result.stderr
        assert sum(len(f.requests) for f in (InteractiveHandler,BackgroundHandler)) == sweep_requests
        assert read(campaign/'state.json') == state
        assert {name:digests(campaign/name) for name in state['completed']} == saved

        failure = copy.deepcopy(matrix);failure['name']='fixture-peer-failure';failure['repeats']=1
        failure['stages'][0]['streams']['background']['load']['rates']=[2]
        failure_path=output/'failure.json';failure_path.write_text(json.dumps(failure,indent=2)+'\n')
        failure_run=output/'peer-failure'
        BackgroundHandler.failure_peer_baseline=len(InteractiveHandler.requests)
        BackgroundHandler.failures=True
        result=run('failed-peer','matrix-run',failure_path,failure_run)
        assert result.returncode != 0, result.stdout+result.stderr
        rejected=read(failure_run/'state.json')
        assert rejected['status']=='evidence_invalid' and not rejected['completed'], rejected
        attempts=list(failure_run.glob('row-*-attempt-*'));assert len(attempts)==1, attempts
        first=attempts[0]
        assert read(first/'summary.json')['evidence']=='invalid'
        for stream in ('interactive','background'):
            for artifact in ('command.json','execution.json','summary.json','manifest.json','aiperf.log'):
                assert (first/stream/artifact).is_file(), (stream,artifact)
        assert len(InteractiveHandler.requests)>BackgroundHandler.failure_peer_baseline,'No healthy-peer traffic was recorded'
        failed_digests=digests(first)
        BackgroundHandler.failures=False
        result=run('failed-peer-resume','matrix-run',failure_path,failure_run,resume=True)
        assert result.returncode == 0, result.stdout+result.stderr
        resumed=read(failure_run/'state.json')
        assert resumed['status']=='complete' and len(resumed['completed'])==1, resumed
        assert resumed['completed'][0].endswith('attempt-002'), resumed
        assert digests(first)==failed_digests, 'Resume changed the failed attempt'
        validate_group(failure_run/resumed['completed'][0],failure['min_overlap_seconds'])
        for fixture in (InteractiveHandler,BackgroundHandler):
            assert all(row['authorized'] and row['path']=='/v1/chat/completions' and row['model']=='fixture-model' and row['payload'].get('stream') is True for row in fixture.requests)
        total=sum(len(f.requests) for f in (InteractiveHandler,BackgroundHandler))
        assert total <= 96, total
        result={'status':'pass','accepted_sweep_groups':6,'groups':groups,'sweep_requests':sweep_requests,
                'total_requests':total,'completed_resume_sent_requests':0,'failed_attempt_preserved':True,
                'failed_group_repeated_as_a_whole':True,'artifacts':str(output)}
        (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result),flush=True)
    finally:
        (output/'observed-request-counts.json').write_text(json.dumps({name:len(fixture.requests) for name,fixture in [('interactive',InteractiveHandler),('background',BackgroundHandler)]},indent=2)+'\n')
        for server in servers:
            server.shutdown();server.server_close()
        for thread in threads:
            thread.join(timeout=2)


if __name__ == '__main__':
    main()
