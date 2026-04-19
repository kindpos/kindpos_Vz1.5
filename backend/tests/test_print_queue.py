"""
Tests for PrintJobQueue — local SQLite-based print job queue.
"""

import pytest
from app.printing.print_queue import PrintJobQueue


@pytest.fixture
async def queue(tmp_path):
    q = PrintJobQueue(db_path=str(tmp_path / "test_queue.db"))
    await q.connect()
    yield q
    await q.close()


def _enqueue_kwargs(**overrides):
    """Default kwargs for enqueue()."""
    kw = {
        'order_id': 'order-001',
        'template_id': 'guest_receipt',
        'printer_mac': 'AA:BB:CC:DD:EE:FF',
        'ticket_number': '1001',
        'context': {'restaurant_name': 'Test'},
    }
    kw.update(overrides)
    return kw


class TestPrintJobQueue:

    async def test_enqueue_returns_job_id(self, queue):
        job_id = await queue.enqueue(**_enqueue_kwargs())
        assert isinstance(job_id, str)
        assert len(job_id) > 0

    async def test_enqueue_and_get_pending(self, queue):
        await queue.enqueue(**_enqueue_kwargs(order_id='o1'))
        await queue.enqueue(**_enqueue_kwargs(order_id='o2'))
        await queue.enqueue(**_enqueue_kwargs(order_id='o3'))

        pending = await queue.get_pending_jobs()
        assert len(pending) == 3

    async def test_mark_sent(self, queue):
        job_id = await queue.enqueue(**_enqueue_kwargs())
        await queue.mark_sent(job_id, 1)

        pending = await queue.get_pending_jobs()
        assert len(pending) == 1
        assert pending[0]['status'] == 'sent'
        assert pending[0]['attempt_count'] == 1

    async def test_mark_completed(self, queue):
        job_id = await queue.enqueue(**_enqueue_kwargs())
        await queue.mark_sent(job_id, 1)
        await queue.mark_completed(job_id)

        pending = await queue.get_pending_jobs()
        assert len(pending) == 0

    async def test_mark_failed(self, queue):
        job_id = await queue.enqueue(**_enqueue_kwargs())
        await queue.mark_failed(job_id)

        failed = await queue.get_failed_jobs()
        assert len(failed) == 1

        pending = await queue.get_pending_jobs()
        assert len(pending) == 0

    async def test_reset_for_retry(self, queue):
        job_id = await queue.enqueue(**_enqueue_kwargs())
        await queue.mark_failed(job_id)

        failed = await queue.get_failed_jobs()
        assert len(failed) == 1

        await queue.reset_for_retry(job_id)

        pending = await queue.get_pending_jobs()
        assert len(pending) == 1
        assert pending[0]['status'] == 'queued'
        assert pending[0]['attempt_count'] == 0

    async def test_dismiss_job(self, queue):
        job_id = await queue.enqueue(**_enqueue_kwargs())
        await queue.dismiss_job(job_id)

        pending = await queue.get_pending_jobs()
        assert len(pending) == 0

        failed = await queue.get_failed_jobs()
        assert len(failed) == 0

    async def test_multiple_jobs_order(self, queue):
        ids = []
        for i in range(3):
            jid = await queue.enqueue(**_enqueue_kwargs(order_id=f'order-{i}'))
            ids.append(jid)

        pending = await queue.get_pending_jobs()
        assert len(pending) == 3
        # Should be in creation order
        for i, job in enumerate(pending):
            assert job['job_id'] == ids[i]

    async def test_completed_not_in_pending(self, queue):
        job_id = await queue.enqueue(**_enqueue_kwargs())
        await queue.mark_sent(job_id, 1)
        await queue.mark_completed(job_id)

        # Enqueue a second job that stays pending
        await queue.enqueue(**_enqueue_kwargs(order_id='order-002'))

        pending = await queue.get_pending_jobs()
        assert len(pending) == 1
        assert pending[0]['order_id'] == 'order-002'
