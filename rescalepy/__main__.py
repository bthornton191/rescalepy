import argparse
import logging
from pathlib import Path
import sys
from .client import Client
from .config import get_config, set_api_key, set_config


def main():
    parser = argparse.ArgumentParser('rescalepy',
                                     description='Submit, monitor, and download jobs on Rescale')
    subparsers = parser.add_subparsers(title='subcommands', dest='subcommand', required=True)
    submit_parser = subparsers.add_parser('submit', help='Submit a job')
    submit_parser.add_argument('name', help='Name of the job')
    submit_parser.add_argument('input_files', type=Path, nargs='+', help='Input files for the job')
    submit_parser.add_argument('--software-code', help='Software code for the job', default=None)
    submit_parser.add_argument('--version', help='Version of the software', default=None)
    submit_parser.add_argument('--command', help='Command to run the job', default=None)
    submit_parser.add_argument('--project-id', help='Project ID for the job', default=None)
    submit_parser.add_argument('--core-type', help='Core type for the job', default=None)
    submit_parser.add_argument('--n-cores', type=int, help='Number of cores for the job', default=1)

    config_parser = subparsers.add_parser('config', help='Configure Rescale API key and default parameters')
    config_parser.add_argument('--api-key', help='Rescale API key', default=None)
    config_parser.add_argument('--software-code', help='Default software code', default=None)
    config_parser.add_argument('--version', help='Default software version', default=None)
    config_parser.add_argument('--command', help='Default command to run jobs', default=None)
    config_parser.add_argument('--project-id', help='Default project ID for jobs', default=None)
    config_parser.add_argument('--core-type', help='Default core type for jobs', default=None)
    config_parser.add_argument('--n-cores', help='Default number of cores for jobs', default=None)

    monitor_parser = subparsers.add_parser('monitor', help='Monitor a job')
    monitor_parser.add_argument('job-id', help='ID of the job to monitor')
    monitor_parser.add_argument('--api-key', help='Rescale API key', default=None)

    download_parser = subparsers.add_parser('download', help='Download results of a job')
    download_parser.add_argument('job-id', help='ID of the job to download results from')
    download_parser.add_argument('output-dir', type=Path, help='Directory to download results to')

    # Batch subcommands
    batch_parser = subparsers.add_parser('batch', help='Manage batch jobs')
    batch_subparsers = batch_parser.add_subparsers(title='batch commands', dest='batch_command', required=True)

    batch_status_parser = batch_subparsers.add_parser('status', help='Show batch status from rescale.json')

    batch_resume_parser = batch_subparsers.add_parser('resume', help='Resume monitoring/downloading from rescale.json')
    batch_resume_parser.add_argument('--max-workers', type=int, default=5, help='Max concurrent operations')
    batch_resume_parser.add_argument('--skip-existing', action='store_true', help='Skip downloading existing files')
    batch_resume_parser.add_argument('--poll-interval', type=int, default=30, help='Seconds between status polls')

    if len(sys.argv) == 1:
        parser.print_help()
        parser.exit()

    args = vars(parser.parse_args())
    subcommand = args.pop('subcommand')

    if subcommand == 'submit':
        get_defaults(args)
        client = Client(args.get('api_key'))
        job_id = client.create_job(
            name=args['name'],
            input_files=args['input_files'],
            software_code=args['software_code'],
            version=args['version'],
            command=args['command'],
            project_id=args['project_id'],
            core_type=args['core_type'],
            n_cores=args['n_cores'],
        )
        print(f'Job created with ID: {job_id}')
        success = client.submit_job(job_id)

        if success:
            print(f'Job {job_id} submitted successfully')
        else:
            print(f'Failed to submit job {job_id}')

    elif subcommand == 'config':
        for key, val in args.items():
            if val is not None:
                if key == 'api_key':
                    set_api_key(val)
                else:
                    set_config(f'default_{key}', val)

    elif subcommand == 'monitor':
        get_defaults(args)
        client = Client(args['api_key'])
        client.wait_for_job(args['job_id'])

    elif subcommand == 'download':
        get_defaults(args)
        client = Client(args['api_key'])
        client.download_all_results(args['job_id'], args['output_dir'])

    elif subcommand == 'batch':
        # Configure logging for batch commands
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        from .batch import BatchRunner

        if args['batch_command'] == 'status':
            BatchRunner.status()

        elif args['batch_command'] == 'resume':
            client = Client()
            runner = BatchRunner.resume(
                client=client,
                max_workers=args['max_workers'],
                skip_existing=args['skip_existing'],
                poll_interval=args['poll_interval'],
            )
            runner.resume_monitoring()


def get_defaults(args):
    for key, val in args.items():
        if val is None:
            args[key] = get_config(f'default_{key}')


if __name__ == '__main__':
    main()
