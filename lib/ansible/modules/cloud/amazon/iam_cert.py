#!/usr/bin/python
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.
ANSIBLE_METADATA = {'metadata_version': '1.0',
                    'status': ['preview'],
                    'supported_by': 'community'}


DOCUMENTATION = '''
---
module: iam_cert
short_description: Manage server certificates for use on ELBs and CloudFront
description:
     - Allows for the management of server certificates
version_added: "2.0"
options:
  name:
    description:
      - Name of certificate to add, update or remove.
    required: true
  new_name:
    description:
      - When present, this will update the name of the cert with the value passed here.
    required: false
  new_path:
    description:
      - When present, this will update the path of the cert with the value passed here.
    required: false
  state:
    description:
      - Whether to create, delete certificate. When present is specified it will attempt to make an update if new_path or new_name is specified.
    required: true
    default: null
    choices: [ "present", "absent" ]
  path:
    description:
      - When creating or updating, specify the desired path of the certificate
    required: false
    default: "/"
  cert_chain:
    description:
      - The CA certificate chain in PEM encoded format.
      - Note that prior to 2.4, this parameter expected a path to a file. Since 2.4 this is now accomplished using a lookup plugin. See examples for detail
    required: false
    default: null
  cert:
    description:
      - The certificate body in PEM encoded format.
      - Note that prior to 2.4, this parameter expected a path to a file. Since 2.4 this is now accomplished using a lookup plugin. See examples for detail
    required: false
  key:
    description:
      - The key of the certificate in PEM encoded format.
      - Note that prior to 2.4, this parameter expected a path to a file. Since 2.4 this is now accomplished using a lookup plugin. See examples for detail
  dup_ok:
    description:
      - By default the module will not upload a certificate that is already uploaded into AWS. If set to True, it will upload the certificate as
        long as the name is unique.
    required: false
    default: False


requirements: [ "boto" ]
author: Jonathan I. Davila
extends_documentation_fragment:
    - aws
    - ec2
'''

EXAMPLES = '''
# Basic server certificate upload from local file
- iam_cert:
    name: very_ssl
    state: present
    cert: "{{ lookup('file', 'path/to/cert') }}"
    key: "{{ lookup('file', 'path/to/key') }}"
    cert_chain: "{{ lookup('file', 'path/to/certchain') }}"

# Server certificate upload using key string
- iam_cert:
    name: very_ssl
    state: present
    path: "/a/cert/path/"
    cert: body_of_somecert
    key: vault_body_of_privcertkey
    cert_chain: body_of_myverytrustedchain
'''
import json
import sys
try:
    import boto
    import boto.iam
    import boto.ec2
    HAS_BOTO = True
except ImportError:
    HAS_BOTO = False

def boto_exception(err):
    '''generic error message handler'''
    if hasattr(err, 'error_message'):
        error = err.error_message
    elif hasattr(err, 'message'):
        error = err.message
    else:
        error = '%s: %s' % (Exception, err)

    return error

def cert_meta(iam, name):
    opath       = iam.get_server_certificate(name).get_server_certificate_result.\
        server_certificate.\
        server_certificate_metadata.\
        path
    ocert       = iam.get_server_certificate(name).get_server_certificate_result.\
                                                 server_certificate.\
                                                 certificate_body
    ocert_id    = iam.get_server_certificate(name).get_server_certificate_result.\
                                                 server_certificate.\
                                                 server_certificate_metadata.\
                                                 server_certificate_id
    upload_date = iam.get_server_certificate(name).get_server_certificate_result.\
                                                 server_certificate.\
                                                 server_certificate_metadata.\
                                                 upload_date
    exp         = iam.get_server_certificate(name).get_server_certificate_result.\
                                                 server_certificate.\
                                                 server_certificate_metadata.\
                                                 expiration
    return opath, ocert, ocert_id, upload_date, exp

def dup_check(module, iam, name, new_name, cert, orig_cert_names, orig_cert_bodies, dup_ok):
    update=False
    if any(ct in orig_cert_names for ct in [name, new_name]):
        for i_name in [name, new_name]:
            if i_name is None:
                continue

            if cert is not None:
                try:
                    c_index=orig_cert_names.index(i_name)
                except NameError:
                    continue
                else:
                    # NOTE: remove the carriage return to strictly compare the cert bodies.
                    slug_cert = cert.replace('\r', '')
                    slug_orig_cert_bodies = orig_cert_bodies[c_index].replace('\r', '')
                    if slug_orig_cert_bodies == slug_cert:
                        update=True
                        break
                    elif slug_orig_cert_bodies != slug_cert:
                        module.fail_json(changed=False, msg='A cert with the name %s already exists and'
                                                           ' has a different certificate body associated'
                                                           ' with it. Certificates cannot have the same name' % i_name)
            else:
                update=True
                break
    elif cert in orig_cert_bodies and not dup_ok:
        for crt_name, crt_body in zip(orig_cert_names, orig_cert_bodies):
            if crt_body == cert:
                module.fail_json(changed=False, msg='This certificate already'
                                                    ' exists under the name %s' % crt_name)

    return update


def cert_action(module, iam, name, cpath, new_name, new_path, state,
                cert, key, chain, orig_cert_names, orig_cert_bodies, dup_ok):
    if state == 'present':
        update = dup_check(module, iam, name, new_name, cert, orig_cert_names,
                           orig_cert_bodies, dup_ok)
        if update:
            opath, ocert, ocert_id, upload_date, exp = cert_meta(iam, name)
            changed=True
            if new_name and new_path:
                iam.update_server_cert(name, new_cert_name=new_name, new_path=new_path)
                module.exit_json(changed=changed, original_name=name, new_name=new_name,
                                 original_path=opath, new_path=new_path, cert_body=ocert,
                                 upload_date=upload_date, expiration_date=exp)
            elif new_name and not new_path:
                iam.update_server_cert(name, new_cert_name=new_name)
                module.exit_json(changed=changed, original_name=name, new_name=new_name,
                                 cert_path=opath, cert_body=ocert,
                                 upload_date=upload_date, expiration_date=exp)
            elif not new_name and new_path:
                iam.update_server_cert(name, new_path=new_path)
                module.exit_json(changed=changed, name=new_name,
                                 original_path=opath, new_path=new_path, cert_body=ocert,
                                 upload_date=upload_date, expiration_date=exp)
            else:
                changed=False
                module.exit_json(changed=changed, name=name, cert_path=opath, cert_body=ocert,
                                 upload_date=upload_date, expiration_date=exp,
                                 msg='No new path or name specified. No changes made')
        else:
            changed=True
            iam.upload_server_cert(name, cert, key, cert_chain=chain, path=cpath)
            opath, ocert, ocert_id, upload_date, exp = cert_meta(iam, name)
            module.exit_json(changed=changed, name=name, cert_path=opath, cert_body=ocert,
                                 upload_date=upload_date, expiration_date=exp)
    elif state == 'absent':
        if name in orig_cert_names:
            changed=True
            iam.delete_server_cert(name)
            module.exit_json(changed=changed, deleted_cert=name)
        else:
            changed=False
            module.exit_json(changed=changed, msg='Certificate with the name %s already absent' % name)

def main():
    argument_spec = ec2_argument_spec()
    argument_spec.update(dict(
        state=dict(
            default=None, required=True, choices=['present', 'absent']),
        name=dict(default=None, required=False),
        cert=dict(default=None, required=False),
        key=dict(default=None, required=False, no_log=True),
        cert_chain=dict(default=None, required=False),
        new_name=dict(default=None, required=False),
        path=dict(default='/', required=False),
        new_path=dict(default=None, required=False),
        dup_ok=dict(default=False, required=False, type='bool')
    )
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        mutually_exclusive=[],
    )

    if not HAS_BOTO:
        module.fail_json(msg="Boto is required for this module")

    region, ec2_url, aws_connect_kwargs = get_aws_connection_info(module)

    try:
        if region:
            iam = connect_to_aws(boto.iam, region, **aws_connect_kwargs)
        else:
            iam = boto.iam.connection.IAMConnection(**aws_connect_kwargs)
    except boto.exception.NoAuthHandlerFound as e:
        module.fail_json(msg=str(e))

    state = module.params.get('state')
    name = module.params.get('name')
    path = module.params.get('path')
    new_name = module.params.get('new_name')
    new_path = module.params.get('new_path')
    cert_chain = module.params.get('cert_chain')
    dup_ok = module.params.get('dup_ok')
    if state == 'present':
        if module.params.get('cert') is not None:
            cert = module.params.get('cert')
        if module.params.get('key') is not None:
            key = module.params.get('key')
        if module.params.get('cert_chain') is not None:
            cert_chain = module.params.get('cert_chain')
    else:
        key=cert=chain=None

    orig_certs = [ctb['server_certificate_name'] for ctb in \
                                                    iam.get_all_server_certs().\
                                                    list_server_certificates_result.\
                                                    server_certificate_metadata_list]
    orig_bodies = [iam.get_server_certificate(thing).\
                  get_server_certificate_result.\
                  certificate_body \
                  for thing in orig_certs]
    if new_name == name:
        new_name = None
    if new_path == path:
        new_path = None

    changed = False
    try:
        cert_action(module, iam, name, path, new_name, new_path, state,
                cert, key, cert_chain, orig_certs, orig_bodies, dup_ok)
    except boto.exception.BotoServerError as err:
        module.fail_json(changed=changed, msg=str(err), debug=[cert,key])


from ansible.module_utils.basic import *
from ansible.module_utils.ec2 import *

if __name__ == '__main__':
    main()
