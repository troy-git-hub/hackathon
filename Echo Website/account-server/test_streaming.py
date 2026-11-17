import asyncio
import json
import unittest
from unittest.mock import patch
import model_stream
import test_accounts as fixtures
app=fixtures.app


class StreamingTests(unittest.TestCase):
    def setUp(self):
        fixtures.AccountTests.setUp(self)
        with app.db(True) as c:c.execute("UPDATE users SET balance=100000")
    tearDown=fixtures.AccountTests.tearDown
    admin=fixtures.AccountTests.admin
    inference_body=fixtures.AccountTests.inference_body

    def test_incremental_answer_and_one_receipt(self):
        self.admin();body=self.inference_body();body['stream']=True
        async def chunks(task,context):
            yield 'reasoning',{'text':'推理片段'}
            await asyncio.sleep(.01)
            yield 'delta',{'text':'第一句'}
            yield 'delta',{'text':'第二句'}
            yield 'usage',{'prompt_tokens':20,'completion_tokens':12}
            yield 'finish',{'reason':'stop'}
        with patch.object(model_stream,'upstream',chunks):
            r=self.client.post('/v1/echo/inference',json=body)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.headers['x-accel-buffering'],'no')
        self.assertEqual(r.text.count('event: delta'),2)
        self.assertIn('event: reasoning',r.text)
        events=[json.loads(line[6:]) for line in r.text.splitlines() if line.startswith('data: ')]
        receipt=events[-1]
        self.assertEqual(receipt['result']['text'],'第一句第二句')
        self.assertNotIn('reasoning',receipt['result'])
        replay=self.client.post('/v1/echo/inference',json=body)
        self.assertEqual(replay.json()['account']['charged_points'],receipt['account']['charged_points'])
        with app.db() as c:
            row=c.execute('SELECT * FROM inference_requests').fetchone()
            self.assertEqual(row['state'],'succeeded');self.assertEqual(row['output_tokens'],12)
            self.assertEqual(c.execute("SELECT count(*) FROM ledger WHERE reference LIKE 'inference:%'").fetchone()[0],1)

    def test_partial_failure_refunds_and_never_completes(self):
        self.admin();body=self.inference_body();body['stream']=True
        async def broken(task,context):
            yield 'delta',{'text':'未完成'}
            raise RuntimeError('SECRET upstream diagnostic')
        with app.db() as c:before=c.execute('SELECT balance FROM users').fetchone()[0]
        with patch.object(model_stream,'upstream',broken):r=self.client.post('/v1/echo/inference',json=body)
        self.assertIn('event: error',r.text);self.assertNotIn('event: done',r.text)
        self.assertNotIn('SECRET',r.text)
        with app.db() as c:
            self.assertEqual(c.execute('SELECT balance FROM users').fetchone()[0],before)
            self.assertEqual(c.execute('SELECT state FROM inference_requests').fetchone()[0],'failed')

    def test_invalid_effort_rejected_before_debit(self):
        self.admin();body=self.inference_body();body['stream']=True;body['context']['reasoning_effort']='unbounded'
        self.assertEqual(self.client.post('/v1/echo/inference',json=body).status_code,400)
        with app.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM inference_requests').fetchone()[0],0)


if __name__=='__main__':unittest.main()
