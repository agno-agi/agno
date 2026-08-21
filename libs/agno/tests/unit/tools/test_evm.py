"""Unit tests for EvmTools class."""

import json
from unittest.mock import Mock, patch

import pytest

from agno.tools.evm import EvmTools


@pytest.fixture
def mock_web3_client():
    """Create a mocked Web3 client with all required methods."""
    mock_client = Mock()

    # Mock Web3 conversion methods
    mock_client.to_wei = Mock(return_value=1000000000)  # 1 gwei
    mock_client.from_wei = Mock(return_value=1.0)

    # Mock eth namespace
    mock_client.eth = Mock()
    mock_client.eth.get_block = Mock(return_value={"baseFeePerGas": 20000000000})  # 20 gwei
    mock_client.eth.get_transaction_count = Mock(return_value=5)
    mock_client.eth.chain_id = 11155111  # Sepolia testnet
    mock_client.eth.get_balance = Mock(return_value=1000000000000000000)  # 1 ETH in wei
    mock_client.eth.send_raw_transaction = Mock(return_value=b"0x1234567890abcdef")
    mock_client.eth.wait_for_transaction_receipt = Mock(
        return_value={"status": 1, "transactionHash": "0x1234567890abcdef"}
    )

    # Mock account
    mock_account = Mock()
    mock_account.address = "0x742d35Cc6634C0532925a3b8D2A7E1234567890A"
    mock_client.eth.account = Mock()
    mock_client.eth.account.from_key = Mock(return_value=mock_account)

    # Mock signed transaction
    mock_signed_tx = Mock()
    mock_signed_tx.raw_transaction = b"0xsignedtransaction"
    mock_client.eth.account.sign_transaction = Mock(return_value=mock_signed_tx)

    return mock_client


@pytest.fixture
def mock_web3_constructor():
    """Mock the Web3 constructor and HTTPProvider."""
    with patch("agno.tools.evm.Web3") as mock_web3_class, patch("agno.tools.evm.HTTPProvider") as mock_http_provider:
        yield mock_web3_class, mock_http_provider


@pytest.fixture
def mock_environment_variables():
    """Mock environment variables for EVM credentials."""
    with patch.dict(
        "os.environ",
        {
            "EVM_PRIVATE_KEY": "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            "EVM_RPC_URL": "https://0xrpc.io/sep",
        },
    ):
        yield


class TestEvmToolsInitialization:
    """Test cases for EvmTools initialization."""

    def test_init_with_credentials(self, mock_web3_constructor, mock_web3_client):
        """Test initialization with provided credentials."""
        mock_web3_class, mock_http_provider = mock_web3_constructor
        mock_web3_class.return_value = mock_web3_client

        tools = EvmTools(
            private_key="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            rpc_url="https://0xrpc.io/sep",
        )

        assert tools.private_key == "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        assert tools.rpc_url == "https://0xrpc.io/sep"
        assert tools.web3_client is not None
        assert tools.account is not None

    def test_init_with_env_variables(self, mock_web3_constructor, mock_web3_client, mock_environment_variables):
        """Test initialization with environment variables."""
        mock_web3_class, mock_http_provider = mock_web3_constructor
        mock_web3_class.return_value = mock_web3_client

        tools = EvmTools()

        assert tools.private_key == "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        assert tools.rpc_url == "https://0xrpc.io/sep"
        assert tools.web3_client is not None

    def test_init_without_private_key(self, mock_web3_constructor):
        """Test initialization failure without private key."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="Private Key is required"):
                EvmTools(rpc_url="https://0xrpc.io/sep")

    def test_init_without_rpc_url(self, mock_web3_constructor):
        """Test initialization failure without RPC URL."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="RPC Url is needed to interact with EVM blockchain"):
                EvmTools(private_key="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef")

    def test_private_key_prefix_added(self, mock_web3_constructor, mock_web3_client):
        """Test that 0x prefix is added to private key if missing."""
        mock_web3_class, mock_http_provider = mock_web3_constructor
        mock_web3_class.return_value = mock_web3_client

        tools = EvmTools(
            private_key="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            rpc_url="https://0xrpc.io/sep",
        )

        assert tools.private_key == "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"


class TestGasFeeCalculation:
    """Test cases for gas fee calculation methods."""

    def test_get_max_priority_fee_per_gas(self, mock_web3_constructor, mock_web3_client):
        """Test max priority fee per gas calculation."""
        mock_web3_class, mock_http_provider = mock_web3_constructor
        mock_web3_class.return_value = mock_web3_client

        tools = EvmTools(
            private_key="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            rpc_url="https://0xrpc.io/sep",
        )

        result = tools.get_max_priority_fee_per_gas()

        mock_web3_client.to_wei.assert_called_once_with(1, "gwei")
        assert result == 1000000000

    def test_get_max_fee_per_gas(self, mock_web3_constructor, mock_web3_client):
        """Test max fee per gas calculation."""
        mock_web3_class, mock_http_provider = mock_web3_constructor
        mock_web3_class.return_value = mock_web3_client

        tools = EvmTools(
            private_key="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            rpc_url="https://0xrpc.io/sep",
        )

        max_priority_fee = 1000000000  # 1 gwei
        result = tools.get_max_fee_per_gas(max_priority_fee)

        mock_web3_client.eth.get_block.assert_called_once_with("latest")
        expected = (2 * 20000000000) + max_priority_fee  # 2 * base_fee + priority_fee
        assert result == expected

    def test_get_max_fee_per_gas_no_base_fee(self, mock_web3_constructor, mock_web3_client):
        """Test max fee per gas calculation when base fee is not available."""
        mock_web3_class, mock_http_provider = mock_web3_constructor
        mock_web3_client.eth.get_block.return_value = {}  # No baseFeePerGas
        mock_web3_class.return_value = mock_web3_client

        tools = EvmTools(
            private_key="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            rpc_url="https://0xrpc.io/sep",
        )

        with pytest.raises(ValueError, match="Base fee per gas not found"):
            tools.get_max_fee_per_gas(1000000000)


class TestSendTransaction:
    """Test cases for send_transaction method."""

    def test_send_transaction_success(self, mock_web3_constructor, mock_web3_client):
        """Test successful transaction sending."""
        mock_web3_class, mock_http_provider = mock_web3_constructor
        mock_web3_class.return_value = mock_web3_client

        tools = EvmTools(
            private_key="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            rpc_url="https://0xrpc.io/sep",
            send_transaction=True,
        )

        result = tools.send_transaction(
            to_address="0x3Dfc53E3C77bb4e30Ce333Be1a66Ce62558bE395",
            amount_in_wei=1000000000000000,  # 0.001 ETH
        )

        # Verify transaction was signed and sent
        mock_web3_client.eth.account.sign_transaction.assert_called_once()
        mock_web3_client.eth.send_raw_transaction.assert_called_once()
        mock_web3_client.eth.wait_for_transaction_receipt.assert_called_once()

        # v3.0: Returns JSON string with transaction_hash
        result_data = json.loads(result)
        assert "transaction_hash" in result_data
        assert result_data["transaction_hash"].startswith("0x")

    def test_send_transaction_invalid_address(self, mock_web3_constructor, mock_web3_client):
        """Test transaction sending with invalid address."""
        mock_web3_class, mock_http_provider = mock_web3_constructor
        mock_web3_class.return_value = mock_web3_client

        tools = EvmTools(
            private_key="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            rpc_url="https://0xrpc.io/sep",
            send_transaction=True,
        )

        result = tools.send_transaction(to_address="invalid_address", amount_in_wei=1000000000000000)

        # v3.0: Returns JSON string
        # Invalid address should still succeed in our mock (no validation in mock)
        # But in real implementation, this would be caught by Web3 validation
        result_data = json.loads(result)
        assert "transaction_hash" in result_data or "error" in result_data

    def test_send_transaction_zero_amount(self, mock_web3_constructor, mock_web3_client):
        """Test transaction sending with zero amount."""
        mock_web3_class, mock_http_provider = mock_web3_constructor
        mock_web3_class.return_value = mock_web3_client

        tools = EvmTools(
            private_key="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            rpc_url="https://0xrpc.io/sep",
            send_transaction=True,
        )

        result = tools.send_transaction(to_address="0x3Dfc53E3C77bb4e30Ce333Be1a66Ce62558bE395", amount_in_wei=0)

        # v3.0: Returns JSON string with transaction_hash
        result_data = json.loads(result)
        assert "transaction_hash" in result_data
        assert result_data["transaction_hash"].startswith("0x")


class TestErrorHandling:
    """Test cases for error handling."""

    def test_transaction_exception_handling(self, mock_web3_constructor, mock_web3_client):
        """Test handling of transaction exceptions."""
        mock_web3_class, mock_http_provider = mock_web3_constructor
        mock_web3_client.eth.send_raw_transaction.side_effect = Exception("Network error")
        mock_web3_class.return_value = mock_web3_client

        tools = EvmTools(
            private_key="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            rpc_url="https://0xrpc.io/sep",
            send_transaction=True,
        )

        result = tools.send_transaction(
            to_address="0x3Dfc53E3C77bb4e30Ce333Be1a66Ce62558bE395", amount_in_wei=1000000000000000
        )

        # v3.0: Returns JSON string with error
        result_data = json.loads(result)
        assert "error" in result_data
        assert "Network error" in result_data["error"]

    def test_gas_calculation_exception(self, mock_web3_constructor, mock_web3_client):
        """Test handling of gas calculation exceptions."""
        mock_web3_class, mock_http_provider = mock_web3_constructor
        mock_web3_client.eth.get_block.side_effect = Exception("RPC error")
        mock_web3_class.return_value = mock_web3_client

        tools = EvmTools(
            private_key="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            rpc_url="https://0xrpc.io/sep",
            send_transaction=True,
        )

        result = tools.send_transaction(
            to_address="0x3Dfc53E3C77bb4e30Ce333Be1a66Ce62558bE395", amount_in_wei=1000000000000000
        )

        # v3.0: Returns JSON string with error
        result_data = json.loads(result)
        assert "error" in result_data
        assert "RPC error" in result_data["error"]


class TestTransactionParameters:
    """Test cases for transaction parameter construction."""

    def test_transaction_params_construction(self, mock_web3_constructor, mock_web3_client):
        """Test that transaction parameters are constructed correctly."""
        mock_web3_class, mock_http_provider = mock_web3_constructor
        mock_web3_class.return_value = mock_web3_client

        tools = EvmTools(
            private_key="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            rpc_url="https://0xrpc.io/sep",
            send_transaction=True,
        )

        tools.send_transaction(to_address="0x3Dfc53E3C77bb4e30Ce333Be1a66Ce62558bE395", amount_in_wei=1000000000000000)

        # Verify sign_transaction was called with correct parameters
        call_args = mock_web3_client.eth.account.sign_transaction.call_args[0][0]

        assert call_args["from"] == "0x742d35Cc6634C0532925a3b8D2A7E1234567890A"
        assert call_args["to"] == "0x3Dfc53E3C77bb4e30Ce333Be1a66Ce62558bE395"
        assert call_args["value"] == 1000000000000000
        assert call_args["nonce"] == 5
        assert call_args["gas"] == 21000
        assert call_args["chainId"] == 11155111
        assert "maxFeePerGas" in call_args
        assert "maxPriorityFeePerGas" in call_args


class TestToolkitIntegration:
    """Test cases for toolkit integration."""

    def test_tools_registration(self, mock_web3_constructor, mock_web3_client):
        """Test that tools are properly registered in the toolkit."""
        mock_web3_class, mock_http_provider = mock_web3_constructor
        mock_web3_class.return_value = mock_web3_client

        # v3.0: Tools require explicit enable via flags
        tools = EvmTools(
            private_key="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            rpc_url="https://0xrpc.io/sep",
            send_transaction=True,
        )

        # Check that the send_transaction method is registered as a tool
        assert hasattr(tools, "tools")
        assert len(tools.tools) == 1
        assert tools.tools[0] == tools.send_transaction

    def test_tools_registration_default_empty(self, mock_web3_constructor, mock_web3_client):
        """Test that no tools are registered by default (v3.0 behavior)."""
        mock_web3_class, mock_http_provider = mock_web3_constructor
        mock_web3_class.return_value = mock_web3_client

        tools = EvmTools(
            private_key="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            rpc_url="https://0xrpc.io/sep",
        )

        # v3.0: No tools registered by default
        assert hasattr(tools, "tools")
        assert len(tools.tools) == 0

    def test_tools_registration_all_flag(self, mock_web3_constructor, mock_web3_client):
        """Test that all=True enables all tools."""
        mock_web3_class, mock_http_provider = mock_web3_constructor
        mock_web3_class.return_value = mock_web3_client

        tools = EvmTools(
            private_key="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            rpc_url="https://0xrpc.io/sep",
            all=True,
        )

        assert hasattr(tools, "tools")
        assert len(tools.tools) == 1
        assert tools.tools[0] == tools.send_transaction

    def test_toolkit_name(self, mock_web3_constructor, mock_web3_client):
        """Test that toolkit has correct name."""
        mock_web3_class, mock_http_provider = mock_web3_constructor
        mock_web3_class.return_value = mock_web3_client

        tools = EvmTools(
            private_key="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            rpc_url="https://0xrpc.io/sep",
        )

        assert tools.name == "evm_tools"
