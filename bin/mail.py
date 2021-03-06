#!/opt/splunk/bin/python

import imaplib
import poplib
# import libraries required
import re
import sys
from ssl import SSLError

from mail_constants import *
from mail_exceptions import *
from mail_utils import *
from file_parser import *
from splunklib.modularinput import *

# Define global variables
__author__ = 'seunomosowon'


class Mail(Script):
    """This inherits the class Script from the splunklib.modularinput script
    They must override the get_scheme and stream_events functions, and,
    if the scheme returned by get_scheme has Scheme.use_external_validation
    set to True, the validate_input function.
    """
    APP = __file__.split(os.sep)[-3]

    def __init__(self):
        super(Mail, self).__init__()
        self.realm = REALM
        self.log = EventWriter.log
        self.write_event = EventWriter.write_event
        self.checkpoint_dir = ""

    # noinspection PyShadowingNames
    def get_scheme(self):
        """This overrides the super method from the parent class"""
        scheme = Scheme("Mail Server")
        scheme.description = "Streams events from from a mail server."
        scheme.use_external_validation = True
        name = Argument(
            name="name",
            title="E-mail",
            description="Enter E-mail Address",
            validation="match('name','%s')" % REGEX_EMAIL,
            data_type=Argument.data_type_string,
            required_on_edit=True,
            required_on_create=True
        )
        scheme.add_argument(name)
        protocol = Argument(
            name="protocol",
            title="Protocol",
            description="Collection Protocol (POP3/IMAP)",
            validation="match('protocol','^(POP3|IMAP)$')",
            data_type=Argument.data_type_string,
            required_on_edit=True,
            required_on_create=True
        )
        scheme.add_argument(protocol)
        mailserver = Argument(
            name="mailserver",
            title="Server",
            description="Mail Server (hostname or IP)",
            validation="match('mailserver','%s')" % REGEX_HOSTNAME,
            data_type=Argument.data_type_string,
            required_on_edit=True,
            required_on_create=True
        )
        scheme.add_argument(mailserver)
        is_secure = Argument(
            name="is_secure",
            title="UseSSL",
            description="Enable Protocol over SSL",
            validation="is_bool('is_secure')",
            data_type=Argument.data_type_boolean,
            required_on_edit=True,
            required_on_create=True
        )
        # bool arguments don't display description
        scheme.add_argument(is_secure)
        password = Argument(
            name="password",
            title="Account Password",
            description="Enter Password for mail account",
            data_type=Argument.data_type_string,
            required_on_edit=True,
            required_on_create=True
        )
        # validation="match('password','%s')" % REGEX_PASSWORD,
        scheme.add_argument(password)
        mailbox_cleanup = Argument(
            name="mailbox_cleanup",
            title="Maibox Management",
            description="(delete|delayed|readonly)",
            validation="match('mailbox_cleanup','^(delete|delayed|readonly)$')",
            data_type=Argument.data_type_string,
            required_on_edit=False,
            required_on_create=False
        )
        scheme.add_argument(mailbox_cleanup)
        include_headers = Argument(
            name="include_headers",
            title="Include headers",
            validation="is_bool('include_headers')",
            data_type=Argument.data_type_boolean,
            required_on_edit=False,
            required_on_create=False
        )
        scheme.add_argument(include_headers)
        maintain_rfc = Argument(
            name="maintain_rfc",
            title="Maintain RFC compatability",
            validation="is_bool('maintain_rfc')",
            data_type=Argument.data_type_boolean,
            required_on_edit=False,
            required_on_create=False
        )
        scheme.add_argument(maintain_rfc)
        attach_message_primary = Argument(
            name="attach_message_primary",
            title="Attached messages become primary",
            validation="is_bool('attach_message_primary')",
            data_type=Argument.data_type_boolean,
            required_on_edit=False,
            required_on_create=False
        )
        scheme.add_argument(attach_message_primary)
        return scheme

    # noinspection PyShadowingNames
    def validate_input(self, validation_definition):
        """
        We are using external validation to check if the server is indeed a POP3 server.
        If validate_input does not raise an Exception, the input is assumed to be valid.
        """
        mailserver = validation_definition.parameters["mailserver"]
        is_secure = bool_variable(validation_definition.parameters["is_secure"])
        protocol = validation_definition.parameters["protocol"]
        email_address = validation_definition.metadata["name"]
        match = re.match(REGEX_EMAIL, email_address)
        if not match:
            raise MailExceptionStanzaNotEmail(email_address)
        mail_connectivity_test(server=mailserver, protocol=protocol, is_secure=is_secure)

    def mask_input_password(self):
        """
        This encrypts the password stored in inputs.conf for the input name passed as an argument.
        """
        kwargs = dict(host=self.mailserver, password=PASSWORD_PLACEHOLDER, mailserver=self.mailserver,
                      is_secure=self.is_secure, protocol=self.protocol,
                      mailbox_cleanup=self.mailbox_cleanup, include_headers=self.include_headers, 
                      maintain_rfc=self.maintain_rfc, attach_message_primary=self.attach_message_primary)
        try:
            self.service.inputs[self.username].update(**kwargs).refresh()
        except Exception, e:
            self.disable_input()
            raise Exception("Error updating inputs.conf - %s" % e)

    def get_credential(self):
        """
        This encrypts the password stored in inputs.conf for the input name passed as an argument.
        :return: Returns the input with the encrypted password
        :rtype: StoragePassword
        """
        storagepasswords = self.service.storage_passwords
        if storagepasswords is not None:
            for credential_entity in storagepasswords:
                """ Use password in storage endpoint if realm matches """
                if credential_entity.username == self.username and credential_entity.realm == self.realm:
                    return credential_entity
        else:
            return None

    def encrypt_password(self):
        """
        This encrypts the password stored in inputs.conf for the input name passed as an argument.
        :return: Returns the input with the encrypted password
        :rtype: StoragePassword
        """
        storagepasswords = self.service.storage_passwords
        try:
            sp = storagepasswords.create(password=self.password, username=self.username, realm=self.realm)
        except Exception, e:
            self.disable_input()
            raise Exception("Could not create password entry {%s:%s} in passwords.conf: %s" % (
                self.username, self.realm, e))
        return sp

    def delete_password(self):
        """
        This deletes the password stored in inputs.conf for the input name passed as an argument.
        """
        try:
            self.service.storage_passwords.delete(self.username, self.realm)
        except Exception, e:
            self.disable_input()
            raise Exception("Could not delete credential {%s:%s} from passwords.conf: %s" % (
                self.username, self.realm, e))

    def disable_input(self):
        """
        This disables a modular input given the input name.
        :return: Returns the disabled input
        :rtype: Entity
        """
        self.service.inputs[self.username].disable()

    def save_password(self):
        """
        :return: This returns a StoragePassword with the right credentials,
                    after saving or updating the storage/passwords endpoint
         :rtype: StoragePassword
        """
        cred = self.get_credential()
        if cred:
            if self.password == PASSWORD_PLACEHOLDER:
                """Already encrypted"""
                return cred
            elif self.password:
                """Update password"""
                self.delete_password()
                cred = self.encrypt_password()
                self.mask_input_password()
                return cred
            else:
                raise Exception("Password cannot be empty")
        else:
            if self.password == PASSWORD_PLACEHOLDER or self.password is None:
                raise Exception("Password cannot be empty or : %s" % PASSWORD_PLACEHOLDER)
            else:
                cred = self.encrypt_password()
                self.mask_input_password()
                return cred

    def stream_imap_emails(self):
        """
        :return: This returns a list of the messages retrieved via IMAP
        :rtype: list
        """
        # Define local variables
        credential = self.get_credential()
        if self.is_secure is True:
            mailclient = imaplib.IMAP4_SSL(self.mailserver)
        else:
            mailclient = imaplib.IMAP4(self.mailserver)
        try:
            # mailclient.debug = 4
            self.log(EventWriter.INFO, "IMAP - Connecting to mailbox as %s" % self.username)
            mailclient.login(credential.username, credential.clear_password)
        except imaplib.IMAP4.error:
            raise MailLoginFailed(self.mailserver, credential.username)
        except (socket.error, SSLError) as e:
            raise MailConnectionError(e)
        self.log(EventWriter.INFO, "Listing folders in mailbox=%s" % self.username)
        # with Capturing() as output:
        mailclient.list()
        # self.log(EventWriter.INFO, "IMAP debug - %s" % output)
        if self.mailbox_cleanup == 'delete' or self.mailbox_cleanup == 'delayed':
            imap_readonly_flag = False
        else:
            self.log(EventWriter.INFO, "Accessing mailbox with readonly attribute")
            imap_readonly_flag = IMAP_READONLY_FLAG
        """
        Might want to iterate over all the child folders of inbox in future version
        And Extend the choise of having this readonly, so mails are saved in mailbox.
        Need to move all this into a controller object that can work on email.Message.Message
        """
        mailclient.select('inbox', readonly=imap_readonly_flag)
        status, data = mailclient.uid('search', None, 'ALL')
        if status == 'OK':
            email_ids = data[0].split()
            num_of_messages = len(email_ids)
            if num_of_messages > 0:
                num = 0
                mails_retrieved = 0
                while num != num_of_messages:
                    result, email_data = mailclient.uid('fetch', email_ids[num], '(RFC822)')
                    if result == 'OK':
                        raw_email = email_data[0][1]
                        message_time, message_mid, msg = email_mime.parse_email(
                            raw_email, 
                            self.include_headers,
                            self.maintain_rfc,
                            self.attach_message_primary,
                        )
                        if locate_checkpoint(self.checkpoint_dir, message_mid) and (
                                        self.mailbox_cleanup == 'delayed' or self.mailbox_cleanup == 'delete'):
                            mailclient.uid('store', email_ids[num], '+FLAGS', '(\\Deleted)')
                            mailclient.expunge()
                            self.log(EventWriter.DEBUG, "Found a mail that had already been indexed: %s" % message_mid)
                            # if not locate_checkpoint(...): then message deletion has been delayed until next run
                        elif not locate_checkpoint(self.checkpoint_dir, message_mid):
                            logevent = Event(
                                stanza=self.username,
                                data=msg,
                                host=self.mailserver,
                                source=self.input_name,
                                time="%.3f" % message_time,
                                done=True,
                                unbroken=True
                            )
                            self.write_event(logevent)
                            save_checkpoint(self.checkpoint_dir, message_mid)
                            mails_retrieved += 1
                        if self.mailbox_cleanup == 'delete':
                            mailclient.uid('store', email_ids[num], '+FLAGS', '(\\Deleted)')
                            mailclient.expunge()
                        num += 1
                mailclient.close()
                mailclient.logout()
                self.log(EventWriter.INFO, "Retrieved %d mails from mailbox: %s" % (mails_retrieved, self.username))

    def stream_pop_emails(self):
        """
        :return: This returns a list of the messages retrieved via POP3
        :rtype: list
        """
        credential = self.get_credential()
        try:
            if self.is_secure:
                mailclient = poplib.POP3_SSL(host=self.mailserver)
            else:
                mailclient = poplib.POP3(host=self.mailserver)
        except (socket.error, SSLError) as e:
            raise MailConnectionError(e)
        except poplib.error_proto, e:
            """Some kind of poplib exception: EOF or other"""
            raise MailProtocolError(str(e))
        try:
            mailclient.set_debuglevel(2)
            self.log(EventWriter.INFO, "POP3 - Connecting to mailbox as %s" % self.username)
            self.log(EventWriter.INFO, "POP3 debug: %s" % mailclient.user(credential.username))
            mailclient.set_debuglevel(1)
            self.log(EventWriter.INFO, "POP3 debug: %s" % mailclient.pass_(credential.clear_password))
        except poplib.error_proto:
            raise MailLoginFailed(self.mailserver, credential.username)
        num = 0
        mails_retrieved = 0
        (num_of_messages, totalsize) = mailclient.stat()
        if num_of_messages > 0:
            while num != num_of_messages:
                num += 1
                (header, msg, octets) = mailclient.retr(num)
                raw_email = '\n'.join(msg)
                message_time, message_mid, msg = email_mime.parse_email(
                    raw_email, 
                    self.include_headers, 
                    self.maintain_rfc,
                    self.attach_message_primary,
                )
                if not locate_checkpoint(self.checkpoint_dir, message_mid):
                    """index the mail if it is readonly or if the mail will be deleted"""
                    logevent = Event(
                        stanza=self.username,
                        data=msg,
                        host=self.mailserver,
                        source=self.input_name,
                        time="%.3f" % message_time,
                        done=True,
                        unbroken=True
                    )
                    self.write_event(logevent)
                    save_checkpoint(self.checkpoint_dir, message_mid)
                    mails_retrieved += 1
                    if self.mailbox_cleanup == 'delete':
                        mailclient.dele(num)
                elif locate_checkpoint(self.checkpoint_dir, message_mid) and (
                                self.mailbox_cleanup == 'delayed' or self.mailbox_cleanup == 'delete'):
                    self.log(EventWriter.DEBUG, "Found a mail that had already been indexed: %s" % message_mid)
                    mailclient.dele(num)
            mailclient.quit()
            self.log(EventWriter.INFO, "Retrieved %d mails from mailbox: %s" % (mails_retrieved, self.username))

    def stream_events(self, inputs, ew):
        """This function handles all the action: splunk calls this modular input
        without arguments, streams XML describing the inputs to stdin, and waits
        for XML on stdout describing events.
        If you set use_single_instance to True on the scheme in get_scheme, it
        will pass all the instances of this input to a single instance of this
        script.
        :param inputs: an InputDefinition object
        :type inputs: InputDefinition
        :param ew: an EventWriter object
        :type ew: EventWriter
        """
        input_list = inputs.inputs.popitem()
        """This runs just once since the default self.use_single_instance = False"""
        input_name, input_item = input_list
        self.input_name = input_name
        self.mailserver = input_item["mailserver"]
        self.username = input_name.split("://")[1]
        self.password = input_item["password"]
        self.protocol = input_item['protocol']
        self.include_headers = bool_variable(input_item['include_headers']) or DEFAULT_INCLUDE_HEADERS
        self.maintain_rfc = bool_variable(input_item['maintain_rfc']) or DEFAULT_MAINTAIN_RFC
        self.attach_message_primary = \
            bool_variable(input_item['attach_message_primary']) or DEFAULT_ATTACH_MESSAGE_PRIMARY
        self.is_secure = bool_variable(input_item["is_secure"]) or DEFAULT_PROTOCOL_SECURITY
        self.mailbox_cleanup = input_item['mailbox_cleanup'] or DEFAULT_MAILBOX_CLEANUP
        self.checkpoint_dir = inputs.metadata['checkpoint_dir']
        self.log = ew.log
        self.write_event = ew.write_event
        if not self.is_secure:
            self.log(EventWriter.WARN, "Mail retrieval will not be secure!!"
                                       "This will be unsupported in a future release")
        match = re.match(REGEX_EMAIL, str(self.username))
        if not match:
            ew.log(EventWriter.ERROR, "Modular input name must be an email address")
            self.disable_input()
            raise MailExceptionStanzaNotEmail(self.username)
        self.save_password()
        if "POP3" == self.protocol:
            self.stream_pop_emails()
        elif "IMAP" == self.protocol:
            self.stream_imap_emails()
        else:
            ew.log(EventWriter.DEBUG, "Protocol must be either POP3 or IMAP")
            self.disable_input()
            raise MailExceptionInvalidProtocol


if __name__ == "__main__":
    sys.exit(Mail().run(sys.argv))
