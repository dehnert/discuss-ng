#!/usr/bin/python

import argparse
import email.parser
import mailbox
import re
import sys

import discuss
import discuss.rpc

DEFAULT_SUBJECT = "No subject found in mail header"

_debug = False
def debug(msg, *args):
    if _debug:
        print msg % args


def re_compile_all(*res):
    return [re.compile('^'+r+'$', re.I) for r in res]

default_list = re_compile_all(
    'to', 'from', '(?!delivered).*-to', '.*-from', 'date',
    'message-id', 'mime-version', 'content-.*',
)
subj_list = re_compile_all('subject')
inreplyto = re_compile_all('in-reply-to')
from_list = re_compile_all('from')

def choose_header_res(args):
    if args.all:
        accept = re_compile_all('.*')
    else:
        accept = []
        if args.defaults:
            accept.extend(default_list)
        accept.extend(re_compile_all(*args.accept))
    return accept, re_compile_all(*args.reject)

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mbox', help='mbox file to use, instead of reading just one message from stdin')
    parser.add_argument('-d', '--defaults', help='retain default fields', action='store_true')
    parser.add_argument('-A', '--all', help='retain all fields', action='store_true')
    parser.add_argument('-a', '--accept', help='accept the specified field', action='append', default=[])
    parser.add_argument('-r', '--reject', help='reject the specified field', action='append', default=[])
    parser.add_argument('-s', '--subject-match', type=int, default=20, help='number of messages backward to look for matching subjects')
    parser.add_argument('-D', '--debug', help='enable debugging output', action='store_true')
    parser.add_argument('name', help='name of meeting')
    args = parser.parse_args()

    args.accept_res, args.reject_res = choose_header_res(args)
    def keep_header(header):
        return list_compare(header, args.accept_res) and not list_compare(header, args.reject_res)
    args.keep_header = keep_header

    if '/' not in args.name:
        args.name = '/var/spool/discuss/' + args.name

    global _debug
    _debug = args.debug
    return args

def get_meeting(path):
    rpc = discuss.rpc.RPCLocalClient
    cl = discuss.Client('localhost', RPCClient=rpc)
    meeting = discuss.Meeting(cl, path)
    return meeting

def list_compare(field_name, res):
    return any([r.match(field_name) for r in res])

def extract_full_name(name):
    # XXX: do the appropriate parsing
    return name

def process_email(meeting, message, keep_header, subject_match):
    subject = None
    in_reply_to = None
    signature = None
    for header, value in message.items():
        if list_compare(header, subj_list):
            subject = value.strip()
        elif list_compare(header, inreplyto):
            in_reply_to = value
        elif list_compare(header, from_list):
            signature = extract_full_name(value)

        if not keep_header(header):
            del message[header]

    send_to_meeting(meeting, message, subject, in_reply_to, signature, subject_match)

def parse_reply_to(meeting, in_reply_to):
    # XXX: the algorithm in dsmail.c is kinda complicated, and I don't think
    # it finds things very often, so postpone.
    return 0

subject_re_match = re.compile("^(re: ?)+", re.I)
def normalize_subject(subject):
    subject = re.sub(subject_re_match, '', subject, count=1)
    subject = subject.strip().lower()
    return subject

def match_by_subject(meeting, count, subject):
    debug("Search for transaction matching %s", subject)
    end = meeting.last
    start = max(end - count, 1)
    trns = meeting.transactions(start, end)
    for trn in reversed(trns):
        debug("  trn=%s", trn.__dict__)
        if normalize_subject(trn.subject) == normalize_subject(subject):
            debug("  Found matching transaction %d (subject: %s)", trn.number, trn.subject)
            return trn.number
    debug("  Found no matching transaction")
    return 0

def send_to_meeting(meeting, message, subject, in_reply_to, signature, subject_match):
    meeting.load_info()
    reply_to_trn = parse_reply_to(meeting, in_reply_to)
    if not reply_to_trn and subject_match and subject:
        reply_to_trn = match_by_subject(meeting, subject_match, subject)
    debug("subject '%s' is a reply to %d in meeting %s", subject, reply_to_trn, meeting.short_name)
    if not subject: subject = DEFAULT_SUBJECT
    try:
        meeting.post(
            message.as_string(), subject,
            reply_to=reply_to_trn, signature=signature
        )
    except discuss.DiscussError as e:
        retry_errs = (discuss.constants.NO_SUCH_TRN, discuss.constants.DELETED_TRN, discuss.constants.NO_ACCESS)
        if e.code in retry_errs and reply_to_trn != 0:
            meeting.post(
                message.as_string(), subject,
                reply_to=0, signature=signature
            )
        else: raise

def main():
    args = parse_args()
    meeting = get_meeting(args.name)
    if args.mbox:
        messages = mailbox.mbox(args.mbox, create=False)
    else:
        parser = email.parser.HeaderParser()
        messages = [parser.parse(sys.stdin)]
    for message in messages:
        process_email(meeting, message, args.keep_header, args.subject_match)

if __name__ == '__main__':
    main()
