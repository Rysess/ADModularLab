# Module: `adcs`

Enterprise Root CA, with optional certificate-services misconfigurations. All
scenarios off by default.

## Requirements

| Key | Value |
| --- | ----- |
| `os` | `windows` |
| `min_instance_type` | `t3.medium` |
| `requires_lab_role` | `dc` |

Runs on any domain-joined Windows host. CA-side work (role install, web
enrollment, interface flags) runs locally; template and ACL writes are
delegated to the `role_dc` host, which holds Enterprise Admin rights.

For ESC8, put the CA on a member server rather than the DC. Relaying a
coerced DC to a CA running on that same DC is blocked by NTLM reflection
protection.

## Usage

```yaml
modules:
  - name: adcs
    vars:
      adcs_esc1: true
      adcs_esc8: true
      adcs_esc11: true
```

Toggles decide what a host gets. Each scenario also carries its own tag
(`esc1`, `esc4`, `esc8`, `esc11`). Through `site.yml` the module include is
tagged `modules`, so a scenario tag selects nothing on its own — it excludes:

```
ansible-playbook site.yml --limit ca01 --tags modules
ansible-playbook site.yml --limit ca01 --tags modules --skip-tags esc8
```

## Scenarios

| Toggle | Configures |
| ------ | ---------- |
| `adcs_esc1` | Client-auth template with requester-supplied subject, no manager approval, enrollable by a low-privilege principal |
| `adcs_esc4` | Template whose object ACL grants a low-privilege principal `GenericAll` |
| `adcs_esc8` | Web enrollment (`/certsrv`) over HTTP with Extended Protection off |
| `adcs_esc11` | `IF_ENFORCEENCRYPTICERTREQUEST` cleared on the ICertRequest interface |

## Variables

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `adcs_ca_common_name` | `{{ domain_netbios }}-CA` | CA common name and publish target |
| `adcs_ca_type` | `EnterpriseRootCA` | CA type |
| `adcs_key_length` | `4096` | CA key size |
| `adcs_hash_algorithm` | `SHA256` | CA signature algorithm |
| `adcs_validity_years` | `10` | CA certificate lifetime |
| `adcs_install_user` | `{{ domain_netbios }}\Administrator` | Enterprise Admin used for the install |
| `adcs_install_password` | DC's Administrator password | From the DC's `host_vars` |
| `adcs_esc1_template` | `LabUserAuth` | ESC1 template name |
| `adcs_esc1_enrollees` | `[Domain Users]` | Principals granted Enroll |
| `adcs_esc4_template` | `LabWebServer` | ESC4 template name |
| `adcs_esc4_writers` | `[Domain Users]` | Principals granted `GenericAll` |

Consumed from Terraform: `domain_netbios`.

## Creates

- `ADCS-Cert-Authority`, `RSAT-ADCS-Mgmt`, and an Enterprise Root CA published
  to the forest.
- Per enabled scenario: certificate templates published to the CA, template
  ACEs, the `ADCS-Web-Enrollment` role, or an amended `InterfaceFlags` value.

## Notes

`Install-AdcsCertificationAuthority` has no desired-state mode and throws when
a CA already exists, so it is guarded on the `Active` value under the CertSvc
configuration key. `Install-AdcsWebEnrollment` is guarded on the `/certsrv`
virtual directory.

## Scope

Certificate templates live in the forest's Configuration partition, so
`adcs_esc1_template` and `adcs_esc4_template` are forest-wide names. Two CAs in
one forest need distinct names or they will fight over the same objects. CAs in
separate forests are independent.

## Footprint

4 GB minimum. Role install and CA configuration take about 5 minutes.
