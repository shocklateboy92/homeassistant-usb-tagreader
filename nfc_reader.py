#!/usr/bin/python3
"""Read NDEF from a T2 tag, output to stdout"""

import sys
import time
import threading
import logging
import os
from typing import Any, Tuple, List
from smartcard.CardConnection import CardConnection
from smartcard.CardMonitoring import CardMonitor, CardObserver
from smartcard.util import toHexString
from smartcard.Exceptions import NoCardException
from smartcard.System import readers
from smartcard.Card import Card

from ndef_decoder import decode_records
from t2_ndef_reader import read_ndef
from mqtt_handler import MQTTHandler

HA_TAG_PREFIX = "https://www.home-assistant.io/tag/"

# Configure logging only when run as main module
if __name__ == "__main__":
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
    )

logger = logging.getLogger(__name__)


def check_pcsc_system() -> bool:
    """Check PC/SC system status and available readers"""
    try:
        logger.info("Checking PC/SC system status...")

        # Get available readers
        available_readers = readers()
        logger.info("Available readers: %d", len(available_readers))

        for i, reader in enumerate(available_readers):
            logger.info("Reader %d: %s", i, reader)

            try:
                # Try to connect to see if there's a card
                connection = reader.createConnection()
                connection.connect()
                logger.info("Reader %d has a card present", i)
                logger.debug("ATR: %s", toHexString(connection.getATR()))
                connection.disconnect()
            except NoCardException:
                logger.info("Reader %d has no card", i)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Reader %d error: %s", i, e)

        if not available_readers:
            logger.error("No PC/SC readers found!")
            return False

        return True

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("PC/SC system check failed: %s", e)
        logger.debug("Exception details:", exc_info=True)
        return False


# Since this is an observer class, it doesn't need public methods
# pylint: disable=too-few-public-methods
class NFCCardObserver(CardObserver):
    """Observer for NFC card insertion and removal events"""

    def __init__(self, mqtt_handler: MQTTHandler) -> None:
        self.cards_processed = 0
        self.processing_lock = threading.Lock()
        self.mqtt_handler = mqtt_handler
        logger.info("NFCCardObserver initialized")

    def update(self, observable, handlers: Tuple[List[Any], List[Card]]) -> None:
        """Called when card events occur"""
        logger.debug(
            "Observer update called with %d handlers", len(handlers) if handlers else 0
        )

        try:
            (addedcards, removedcards) = handlers
            logger.debug(
                "Added cards: %d, Removed cards: %d", len(addedcards), len(removedcards)
            )

            # Handle card insertions
            for card in addedcards:
                logger.info("Card inserted: %s", toHexString(card.atr))
                logger.debug("Starting thread to process card")
                threading.Thread(
                    target=self._process_card, args=(card,), daemon=True
                ).start()

            # Handle card removals
            for card in removedcards:
                logger.info("Card removed: %s", toHexString(card.atr))
                # Publish MQTT state for card removal (no tag present)
                self.mqtt_handler.publish_tag_state(None)

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Error in observer update: %s", e)
            logger.debug("Exception details:", exc_info=True)

    def _process_card(self, card: Card) -> None:
        """Process a card in a separate thread"""
        with self.processing_lock:
            try:
                # Connect to the card
                connection = card.createConnection()
                if not isinstance(connection, CardConnection):
                    logger.error("Invalid card connection type: %s", type(connection))
                    return

                with connection:
                    connection.connect()

                    logger.info("Connected to card")

                    # Read NDEF data
                    data, error = read_ndef(connection)

                    if error:
                        logger.error("Error reading NDEF: %s", error)
                        return

                    if not data:
                        logger.info("No NDEF data found on card")
                        # Still publish MQTT state for cards without NDEF data
                        card_atr = toHexString(card.atr)
                        self.mqtt_handler.publish_tag_state(f"no_ndef_{card_atr}")
                        return

                    # Output hex representation for debugging
                    logger.debug("Raw NDEF data (%d bytes): %s", len(data), data.hex())

                    records = decode_records(data)

                    ha_tag_found = False  # Track if we found a Home Assistant tag

                    logger.info("=== NDEF Records ===")
                    for i, record in enumerate(records):
                        logger.info("Record %d:", i + 1)
                        logger.info("  TNF: %d (%s)", record.tnf, record.tnf_name)
                        logger.info(
                            "  Type: %s (hex: %s)",
                            record.type_str,
                            record.record_type.hex(),
                        )
                        if record.id_str:
                            logger.info("  ID: %s", record.id_str)
                        logger.info("  Payload length: %d bytes", len(record.payload))
                        logger.debug("  Payload (hex): %s", record.payload.hex())
                        logger.debug("  Payload (string): %r", record.payload_str)

                        # Special handling for URI records
                        if record.is_uri_record:
                            uri = record.get_decoded_uri()
                            logger.info("  Decoded URI: %s", uri)

                            # Check if it's a Home Assistant tag
                            if uri and uri.startswith(HA_TAG_PREFIX):
                                tag_id = uri[len(HA_TAG_PREFIX) :]
                                logger.info("  Home Assistant Tag ID: %s", tag_id)
                                ha_tag_found = True

                                # Publish MQTT state for card presence
                                self.mqtt_handler.publish_tag_state(tag_id)

                        # Special handling for Android Application Record (AAR)
                        elif record.is_android_app_record:
                            package_name = record.get_android_package_name()
                            logger.info("  Android Package: %s", package_name)

                        logger.debug(
                            "  Flags: MB=%s, ME=%s, CF=%s, SR=%s, IL=%s",
                            record.message_begin,
                            record.last_record,
                            record.chunked,
                            record.short_record,
                            record.has_id,
                        )

                    # If no Home Assistant tag was found, publish generic tag presence
                    if not ha_tag_found:
                        # Use card ATR as a unique identifier for non-HA tags
                        card_atr = toHexString(card.atr)
                        self.mqtt_handler.publish_tag_state(f"generic_{card_atr}")

                    self.cards_processed += 1
                    logger.info(
                        "--- Card read completed --- (Total: %d)",
                        self.cards_processed,
                    )

            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Error processing card: %s", e)


def main() -> int:
    """Main function - uses observer pattern for card monitoring"""
    logger.info("NFC Reader starting up...")

    # Check PC/SC system first
    if not check_pcsc_system():
        logger.error("PC/SC system check failed - cannot continue")
        return 1

    # Setup MQTT (optional - system can work without it)
    mqtt_handler = MQTTHandler()
    mqtt_handler.setup()

    logger.info("NFC Reader started - waiting for cards...")
    logger.info("Press Ctrl+C to stop")

    observer = None
    try:
        # Create card observer and monitor
        logger.debug("Creating CardObserver...")
        observer = NFCCardObserver(mqtt_handler)

        logger.debug("Creating CardMonitor...")
        card_monitor = CardMonitor()

        logger.debug("Adding observer to monitor...")
        card_monitor.addObserver(observer)

        logger.info("Card monitoring started - place a card on the reader")
        logger.debug("Monitoring thread active, main thread will sleep")

        # Keep the main thread alive and periodically show we're still running
        loop_count = 0
        while True:
            time.sleep(5)  # Check every 5 seconds
            loop_count += 1
            if loop_count % 12 == 0:  # Every minute
                logger.debug("Still monitoring... (%ds elapsed)", loop_count * 5)

    except KeyboardInterrupt:
        cards_count = observer.cards_processed if observer else 0
        logger.info("Shutting down... Processed %d cards.", cards_count)
        return 0
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Unexpected error in main loop: %s", e)
        logger.debug("Exception details:", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
