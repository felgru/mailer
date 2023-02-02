<!--
SPDX-FileCopyrightText: 2023 Felix Gruber <felgru@posteo.net>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Mass mailer script

> send templated emails to a list of receipients

Let's say you want to invite a bunch of people for your birthday party and
you want to each email to contain a salutation with the name of the receipient.
Maybe, you also want to put different text in text in the email for different
groups of people, e.g. because you don't need to remind your family about your
addressen and you want to write the invitation to your friends from your
Spanish class in Spanish.

This is exactly the kind of situation that my mailer script was written for.
You write templates for the emails that you want to send and you create a CSV
file containing in each row the email address of a recipient, the template
that should be used for them and any values that should be filled into the
templated, e.g. their name.
You also need to write a config file containing your sender address and
some information about your mail server.
The mailer script then goes through the CSV file line by line, fills out the
corresponding template and sends off the email from the address that you
specified in the config file.

# Step-by-Step Instructions

## Input files

You need to a CSV file containing at least the following fields:

* `email`: The email address of the recipient.
* `template`: The name of the email template to use.

In addition, you can add arbitrary fields to be used in your templates.
If you add the `firstname` and `lastname` fields they will be used to
construct a name to be displayed in the To address of the email.

Let's say we call this CSV file `birthday.csv`. It's content could look like
```
firstname,lastname,email,template
John,Doe,john.doe@example.com,friends
Bob,,uncle.bob@example.com,family
```
Every other file will then be looked up relative to this CSV file and in
our birthday example, the mailer script would expect the following directory
structure:
```
├── birthday.csv
├── birthday-sender.ini
└── templates
    ├── family
    └── friends
```
The template files use [PEP 292](https://peps.python.org/pep-0292/)'s format,
i.e. if you put in a `$`-sign followed by the name of a field from your CSV
file in a template, it will be replaced with the content of that field.
If you ever want to put a literal `$`-sign in your email, you escape it as `$$`.

The first line of the template file has to start with `Subject: ` and will be
used as the subject line of your email.

Now to the most complicated part: The `...-sender.ini` configuration file.
It is an [INI file](https://docs.python.org/3/library/configparser.html#supported-ini-file-structure)
with a `[sender]` section and at least the variables `name`, `email` and
`smtpserver`.
Optionally, you can also specify `smtpuser` (defaults to the value of the
`email` variable, otherwise) and `smtpport` (defaults to `587`).
A minimal example would look like
```
[sender]
name = My Name
email = myself@example.com
smtpserver = example.com
```

Once you've created all those files, you can run
```shell
./mailer.py check birthday.csv
```
to run some sanity checks on your CSV file and templates.

To check that the templating works as intended, you can also run
```shell
./mailer.py print birthday.csv john.doe@example.com
```
to print the content of the generated email to `john.doe@example.com`,
including any email headers.

If everything is in order, you might then want to send the emails with
```shell
./mailer.py send-all birthday.csv
```
This will ask you for your password to connect to your mailprovider's SMTP
server. Once it has successfully logged in, it will send the emails one by
one. It will create a log file `birthday-sent.log` to keep track of sent
emails. If anything goes wrong, you can re-run the
`mailer.py send-all birthday.csv` command and it will skip any emails that
were already successfully sent.
