# pylint: disable=no-self-use
from __future__ import annotations
from collections import defaultdict
from datetime import date
from typing import Dict, List
import pytest
from allocation import bootstrap
from allocation.domain import commands
from allocation.service_layer import handlers
from allocation.adapters import notifications, repository
from allocation.service_layer import unit_of_work


class FakeRepository(repository.AbstractRepository):
    def __init__(self, products):
        super().__init__()
        self._products = set(products)

    def _add(self, product):
        self._products.add(product)

    def _get(self, sku):
        return next((p for p in self._products if p.sku == sku), None)

    def _get_by_batchref(self, batchref):
        return next(
            (p for p in self._products for b in p.batches if b.reference == batchref),
            None,
        )


class FakeUnitOfWork(unit_of_work.AbstractUnitOfWork):
    def __init__(self):
        self.products = FakeRepository([])
        self.committed = False

    def _commit(self):
        self.committed = True

    def rollback(self):
        pass


class FakeNotifications(notifications.AbstractNotifications):
    def __init__(self):
        self.sent = defaultdict(list)  # type: Dict[str, List[str]]

    def send(self, destination, message):
        self.sent[destination].append(message)


def bootstrap_test_app():
    return bootstrap.bootstrap(
        start_orm=False,
        uow=FakeUnitOfWork(),
        notifications=FakeNotifications(),
        publish=lambda *args: None,
    )


class TestAddBatch:
    def test_for_new_product(self):
        bus = bootstrap_test_app()
        bus.handle(commands.CreateBatch("b1", "SEABREEZE", 100, None))
        assert bus.uow.products.get("SEABREEZE") is not None
        assert bus.uow.committed

    def test_for_existing_product(self):
        bus = bootstrap_test_app()
        bus.handle(commands.CreateBatch("b1", "NIGHTCLUB", 100, None))
        bus.handle(commands.CreateBatch("b2", "NIGHTCLUB", 99, None))
        assert "b2" in [
            b.reference for b in bus.uow.products.get("NIGHTCLUB").batches
        ]


class TestAllocate:
    def test_allocates(self):
        bus = bootstrap_test_app()
        bus.handle(commands.CreateBatch("batch1", "JUNGLE", 100, None))
        bus.handle(commands.Allocate("o1", "JUNGLE", 10))
        [batch] = bus.uow.products.get("JUNGLE").batches
        assert batch.available_quantity == 90

    def test_errors_for_invalid_sku(self):
        bus = bootstrap_test_app()
        bus.handle(commands.CreateBatch("b1", "AREALSKU", 100, None))

        with pytest.raises(handlers.InvalidSku, match="Invalid sku NONEXISTENTSKU"):
            bus.handle(commands.Allocate("o1", "NONEXISTENTSKU", 10))

    def test_commits(self):
        bus = bootstrap_test_app()
        bus.handle(commands.CreateBatch("b1", "FOREST", 100, None))
        bus.handle(commands.Allocate("o1", "FOREST", 10))
        assert bus.uow.committed

    def test_sends_email_on_out_of_stock_error(self):
        fake_notifs = FakeNotifications()
        bus = bootstrap.bootstrap(
            start_orm=False,
            uow=FakeUnitOfWork(),
            notifications=fake_notifs,
            publish=lambda *args: None,
        )
        bus.handle(commands.CreateBatch("b1", "BUSY-STREET", 9, None))
        bus.handle(commands.Allocate("o1", "BUSY-STREET", 10))
        assert fake_notifs.sent["stock@made.com"] == [
            f"Out of stock for BUSY-STREET",
        ]


class TestChangeBatchQuantity:
    def test_changes_available_quantity(self):
        bus = bootstrap_test_app()
        bus.handle(commands.CreateBatch("batch1", "SEABREEZE", 100, None))
        [batch] = bus.uow.products.get(sku="SEABREEZE").batches
        assert batch.available_quantity == 100

        bus.handle(commands.ChangeBatchQuantity("batch1", 50))
        assert batch.available_quantity == 50

    def test_reallocates_if_necessary(self):
        bus = bootstrap_test_app()
        history = [
            commands.CreateBatch("batch1", "NIGHTCLUB", 50, None),
            commands.CreateBatch("batch2", "NIGHTCLUB", 50, date.today()),
            commands.Allocate("order1", "NIGHTCLUB", 20),
            commands.Allocate("order2", "NIGHTCLUB", 20),
        ]
        for msg in history:
            bus.handle(msg)
        [batch1, batch2] = bus.uow.products.get(sku="NIGHTCLUB").batches
        assert batch1.available_quantity == 10
        assert batch2.available_quantity == 50

        bus.handle(commands.ChangeBatchQuantity("batch1", 25))

        # order1 or order2 will be deallocated, so we'll have 25 - 20
        assert batch1.available_quantity == 5
        # and 20 will be reallocated to the next batch
        assert batch2.available_quantity == 30
