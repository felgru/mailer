#!/usr/bin/python3

# SPDX-FileCopyrightText: 2023 Felix Gruber <felgru@posteo.net>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import argparse
from collections import Counter
import configparser
import csv
from dataclasses import dataclass
from email.message import EmailMessage
from getpass import getpass
import json
from pathlib import Path
import smtplib
import ssl
import subprocess
from string import Template
from typing import cast, Literal, Protocol
import uuid


@dataclass
class DisplayAddress:
    email: str
    name: str | None = None

    def __str__(self) -> str:
        if self.name is None:
            return self.email
        else:
            return f'{self.name} <{self.email}>'


@dataclass
class Email:
    subject: str
    body: str
    from_address: DisplayAddress
    to_address: DisplayAddress

    def as_mime(self) -> EmailMessage:
        msg = EmailMessage()
        msg.set_content(self.body)
        msg['Subject'] = self.subject
        msg['From'] = str(self.from_address)
        msg['To'] = str(self.to_address)
        from_email = self.from_address.email
        message_id = '<' + str(uuid.uuid4()) \
                     + from_email[from_email.rfind('@'):] + '>'
        msg['Message-ID'] = message_id
        return msg


class Templates:
    def __init__(self, templates_dir: Path):
        self.templates_dir = templates_dir
        self.templates: dict[str, Template] = {}

    def add_template(self, name: str) -> Template:
        with (self.templates_dir / name).open() as f:
            template = Template(f.read())
        self.templates[name] = template
        return template

    def __getitem__(self, key: str) -> Template:
        try:
            template = self.templates[key]
        except KeyError:
            template = self.add_template(key)
        return template

    def create_message(self,
                       template_name: str,
                       *,
                       content: dict[str, str],
                       sender_address: DisplayAddress,
                       ) -> Email:
        try:
            to_name = '{firstname} {lastname}'.format_map(content)
        except KeyError:
            to_name = None
        to_address = DisplayAddress(name=to_name, email=content['email'])
        filled = self[template_name].substitute(content)
        if not filled.startswith('Subject: '):
            raise RuntimeError(f'Missing Subject line in template {template_name}.')
        end_of_subject = filled.find('\n')
        subject = filled[:end_of_subject].removeprefix('Subject: ')
        body = filled[end_of_subject+1:].lstrip()
        msg = EmailMessage()
        msg.set_content(body)
        msg['Subject'] = subject
        msg['From'] = str(sender_address)
        msg['To'] = to_address
        return Email(
                subject=subject,
                body=body,
                from_address=sender_address,
                to_address=to_address,
                )


class Sender(Protocol):
    def login(self) -> None: ...
    def send_message(self, msg: Email) -> None: ...
    def quit(self) -> None: ...
    def __enter__(self) -> Sender: ...
    def __exit__(self, exc_type, exc_value, traceback) -> None: ...

    @property
    def sender_address(self) -> DisplayAddress: ...


class SMTPSender:
    def __init__(self,
                 sender_address: DisplayAddress,
                 smtpserver: str,
                 smtpuser: str,
                 smtpport: int):
        self.sender_address = sender_address
        self.smtpserver = smtpserver
        self.smtpuser = smtpuser
        self.smtpport = smtpport
        self.smtp = smtplib.SMTP(self.smtpserver, self.smtpport)

    def login(self) -> None:
        password = getpass(f'Password for {self.sender_address.email}: ')
        context = ssl.create_default_context()
        self.smtp.starttls(context=context)
        self.smtp.login(self.smtpuser, password)

    def send_message(self, msg: Email) -> None:
        self.smtp.send_message(msg.as_mime())

    def quit(self) -> None:
        self.smtp.quit()

    def __enter__(self) -> SMTPSender:
        self.login()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.quit()


class ThunderbirdSender:
    def __init__(self,
                 sender_address: DisplayAddress):
        self.sender_address = sender_address

    def login(self) -> None:
        pass

    def send_message(self, msg: Email) -> None:
        options = {'to': str(msg.to_address),
                   'from': str(msg.from_address),
                   'subject': msg.subject,
                   'body': msg.body,
                   #'format': 'text',
                   }
        command = ['thunderbird', '-compose',
                        ','.join(f"{key}='{value}'"
                                 for key, value in options.items())]
        subprocess.run(command)
        reply = input('email sent [Y/n]? ').strip().lower()
        if not reply or reply == 'y':
            # Sent successfully
            return
        elif reply == 'n':
            raise RuntimeError('You said that you didn\'t sent the email.')
        else:
            raise RuntimeError(f'Unexpected reply: {reply!r}')

    def quit(self) -> None:
        pass

    def __enter__(self) -> ThunderbirdSender:
        self.login()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.quit()


def create_sender(cfg_file: Path) -> Sender:
    config = configparser.ConfigParser()
    config.read(cfg_file)
    sender_config = config['sender']
    name = sender_config['name']
    email = sender_config['email']
    sender_address = DisplayAddress(email=email, name=name)
    smtpserver = sender_config.get('smtpserver')
    if smtpserver is None:
        return ThunderbirdSender(sender_address=sender_address)
    smtpuser = sender_config.get('smtpuser', email)
    smtpport = int(sender_config.get('smtpport', '587'))
    return SMTPSender(sender_address=sender_address,
                      smtpserver=smtpserver,
                      smtpuser=smtpuser,
                      smtpport=smtpport)


def read_sender_address(csv_path: Path) -> DisplayAddress:
    sender_path = csv_path.with_name(csv_path.stem + '-sender.ini')
    if not sender_path.exists():
        raise RuntimeError(f'Please configure sender in file {sender_path}.')
    config = configparser.ConfigParser()
    config.read(sender_path)
    sender_config = config['sender']
    name = sender_config['name']
    email = sender_config['email']
    return DisplayAddress(email=email, name=name)


def check_csv(args: argparse.Namespace) -> None:
    with open(args.csv, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        missing_fields = [field for field in ['email', 'template']
                          if field not in cast(str, reader.fieldnames)]
        if missing_fields:
            raise RuntimeError(f'Missing fields in {args.csv}: '
                               f'{", ".join(missing_fields)}')
        emails = Counter[str]()
        templates = set()
        for row in reader:
            emails[row['email']] += 1
            templates.add(row['template'])
        duplicate_emails = [email for email, count in emails.items()
                            if count > 1]
        if duplicate_emails:
            raise RuntimeError(
                'The following email addresses appear in more than one row: '
                + ', '.join(duplicate_emails))
        template_dir = Path(args.csv).parent / 'templates'
        unknown_templates = [template for template in templates
                             if not (template_dir / template).exists()]
        if unknown_templates:
            raise RuntimeError(
                f'The following templates were used in {args.csv}, '
                f'but do not exist: {", ".join(unknown_templates)}')
        instantiated_templates = Templates(template_dir)
        for template in (instantiated_templates[t] for t in templates):
            # TODO: In Python 3.11, we could use template.is_valid() and
            #       template.get_identifiers()
            pass # TODO: Implement check that template is valid and all
                 #       identifiers have been provided in the CSV file.


def print_mail(args: argparse.Namespace) -> None:
    email = args.email_address
    csv_path = Path(args.csv)
    sender = read_sender_address(csv_path)
    template_dir = csv_path.parent / 'templates'
    templates = Templates(template_dir)
    with open(csv_path, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            if row['email'] != email:
                continue
            msg = templates.create_message(
                    row['template'],
                    content=row,
                    sender_address=sender,
            )
            print(msg)
            break
        else:
            raise RuntimeError(f'{email} not found in {args.csv}.')


@dataclass
class LogEntry:
    email: str
    status: Literal['sent', 'failure']
    failure_reason: str | None = None

    @property
    def was_successful(self) -> bool:
        return self.status == 'sent'

    @classmethod
    def success(cls, email: str) -> LogEntry:
        return cls(email=email, status='sent')

    @classmethod
    def failure(cls, email: str, reason: str) -> LogEntry:
        return cls(email=email, status='failure', failure_reason=reason)

    @classmethod
    def from_json(cls, j: str) -> LogEntry:
        content = json.loads(j)
        return cls(**content)

    def to_json(self) -> str:
        d = {'email': self.email,
             'status': self.status,
             }
        if self.failure_reason is not None:
            d['failure_reason'] = self.failure_reason
        return json.dumps(d)


def send_all_emails(args: argparse.Namespace) -> None:
    csv_path = Path(args.csv)
    send_log_path = csv_path.with_name(csv_path.stem + '-sent.log')
    template_dir = csv_path.parent / 'templates'
    templates = Templates(template_dir)
    sender_path = csv_path.with_name(csv_path.stem + '-sender.ini')
    if not sender_path.exists():
        raise RuntimeError(f'Please configure sender in file {sender_path}.')
    status = {}
    if not send_log_path.exists():
        send_log_path.touch()
    else:
        with send_log_path.open() as f:
            for line in f:
                log_entry = LogEntry.from_json(line)
                status[log_entry.email] = log_entry
    with (open(csv_path, newline='') as csvfile,
          send_log_path.open('a') as log_file,
          create_sender(sender_path) as sender):
        reader = csv.DictReader(csvfile)
        for row in reader:
            to = row['email']
            if status.get(to) is not None and status[to].was_successful:
                continue
            try:
                msg = templates.create_message(
                        row['template'],
                        content=row,
                        sender_address=sender.sender_address,
                )
                # print(msg)
                sender.send_message(msg)
                print(f'Sent to {to}')
            except Exception as e:
                log_file.write(LogEntry.failure(email=to, reason=str(e))
                                       .to_json())
                log_file.write('\n')
                raise
            else:
                log_file.write(LogEntry.success(email=row['email'])
                                       .to_json())
                log_file.write('\n')


def create_argparser() -> argparse.ArgumentParser:
    aparser = argparse.ArgumentParser(
            description='Send mail from templates.')

    subparsers = aparser.add_subparsers()
    check = subparsers.add_parser('check')
    check.add_argument(
            'csv',
            help='csv file with email addresses and data to fill into templates')
    check.set_defaults(command=check_csv)
    pmail = subparsers.add_parser('print',
                                  help='print email to given address')
    pmail.add_argument(
            'csv',
            help='csv file with email addresses and data to fill into templates')
    pmail.add_argument(
            'email_address',
            help='email address to print mail for')
    pmail.set_defaults(command=print_mail)
    send_all = subparsers.add_parser('send-all')
    send_all.add_argument(
            'csv',
            help='csv file with email addresses and data to fill into templates')
    send_all.set_defaults(command=send_all_emails)
    return aparser


if __name__ == '__main__':
    aparser = create_argparser()
    args = aparser.parse_args()
    args.command(args)
