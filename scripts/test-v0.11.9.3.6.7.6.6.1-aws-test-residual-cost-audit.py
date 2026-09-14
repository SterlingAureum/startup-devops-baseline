#!/usr/bin/env python3
"""Offline zero-retry error compatibility plus inherited audit behavioral tests."""
import importlib.util
from pathlib import Path
import re
import unittest
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('audit_repair',HERE/'execute-v0.11.9.3.6.7.6.6.1-aws-test-residual-cost-audit.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
spec=importlib.util.spec_from_file_location('audit_fixtures',HERE/'test-v0.11.9.3.6.7.6.6-aws-test-residual-cost-audit.py')
f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
f.m=m
OBSERVED=b'\nAn error occurred (NoSuchBucket) when calling the ListObjectVersions operation (reached max retries: 0): The specified bucket does not exist\n'

class ErrorRepairTests(f.AuditTests):
    def test_observed_no_such_bucket_hash_and_zero_annotation(self):
        self.assertEqual(len(OBSERVED),142)
        self.assertEqual(m.digest(OBSERVED),'ecd76333f2a3c4953915fcb46ab976755f9840211a13e51d3416df3e69d09ac7')
        self.assertTrue(m.absence_error(OBSERVED,b'','list-object-versions',('NoSuchBucket',)))
        self.overrides['s3api','list-object-versions']=(254,b'',OBSERVED)
        result=self.runphase('preflight')
        self.assertEqual(result['status'],'aws-test-residual-cost-audit-preflight-ready-for-separate-approval')
        self.assertFalse(result['full_audit_executed'])
    def test_permission_connection_and_other_errors_with_zero_annotation_rejected(self):
        for code in ('AccessDenied','Forbidden','ExpiredToken','SlowDown','InvalidAccessKeyId'):
            with self.subTest(code=code):
                raw=OBSERVED.replace(b'NoSuchBucket',code.encode())
                self.assertFalse(m.absence_error(raw,b'','list-object-versions',('NoSuchBucket',)))
        self.assertFalse(m.absence_error(b'Could not connect to the endpoint URL',b'','list-object-versions',('NoSuchBucket',)))
    def test_positive_malformed_and_duplicate_retry_annotations_rejected(self):
        for annotation in (b'1',b'2',b'10',b'-1',b'00',b'not-a-number'):
            with self.subTest(annotation=annotation):
                self.assertFalse(m.absence_error(OBSERVED.replace(b'retries: 0',b'retries: '+annotation),b'','list-object-versions',('NoSuchBucket',)))
        twice=OBSERVED.replace(b'operation (reached max retries: 0)',b'operation (reached max retries: 0) (reached max retries: 0)')
        self.assertFalse(m.absence_error(twice,b'','list-object-versions',('NoSuchBucket',)))
    def test_wrong_operation_nonempty_stdout_multiple_errors_still_rejected(self):
        for error,stdout,op in ((OBSERVED,b'{}','list-object-versions'),(OBSERVED,b'','get-role'),(OBSERVED+OBSERVED,b'','list-object-versions'),(OBSERVED+b'other failure\n',b'','list-object-versions')):
            self.assertFalse(m.absence_error(error,stdout,op,('NoSuchBucket',)))
    def test_original_unannotated_error_remains_accepted(self):
        self.assertTrue(m.absence_error(OBSERVED.replace(b' (reached max retries: 0)',b''),b'','list-object-versions',('NoSuchBucket',)))
    def test_known_absence_codes_share_matching_operation_parser(self):
        cases=[('NoSuchBucket','list-object-versions','ListObjectVersions'),
               ('ResourceNotFoundException','describe-secret','DescribeSecret'),
               ('NoSuchEntity','get-open-id-connect-provider','GetOpenIDConnectProvider'),
               ('InvalidVolume.NotFound','describe-volumes','DescribeVolumes'),
               ('AWS.SimpleQueueService.NonExistentQueue','get-queue-attributes','GetQueueAttributes')]
        for code,op,api in cases:
            with self.subTest(code=code):
                raw=('An error occurred ('+code+') when calling the '+api+' operation (reached max retries: 0): fixture only\n').encode()
                self.assertTrue(m.absence_error(raw,b'',op,(code,)))
                self.assertFalse(m.absence_error(raw,b'','other-operation',(code,)))
    def test_successful_whole_flow_with_zero_annotated_absence_errors(self):
        original=self.backend
        def annotated(cmd,out,err,timeout,env):
            rc=original(cmd,out,err,timeout,env)
            if rc:
                raw=err.read_bytes();err.write_bytes(re.sub(rb' operation:',b' operation (reached max retries: 0):',raw))
            return rc
        self.backend=annotated
        self.prepared();result=self.execution()
        self.assertTrue(result['audit_passed']);self.assertFalse(result['mutation_executed']);self.assertFalse(result['automatic_retry_performed'])
    def test_positive_retry_annotation_stops_the_preflight_and_keeps_raw(self):
        self.overrides['s3api','list-object-versions']=(254,b'',OBSERVED.replace(b'retries: 0',b'retries: 1'))
        result=self.runphase('preflight')
        self.assertEqual(result['status'],'aws-test-residual-cost-audit-stopped')
        self.assertEqual(result['stage'],'backup-bucket')
        self.assertFalse(result['audit_attempt_consumed']);self.assertFalse(result['full_audit_executed'])
        self.assertTrue((self.base/'preflight'/'failure.json').exists())
if __name__=='__main__':unittest.main(verbosity=2)
