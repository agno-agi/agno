#!/bin/bash

# Test runner script for agent-os-docker
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker is running
check_docker() {
    if ! docker info > /dev/null 2>&1; then
        print_error "Docker is not running. Please start Docker and try again."
        exit 1
    fi
    print_status "Docker is running"
}

# Check if Docker Compose is available
check_docker_compose() {
    if ! command -v docker-compose &> /dev/null; then
        print_error "docker-compose is not installed. Please install it and try again."
        exit 1
    fi
    print_status "Docker Compose is available"
}

# Start the containers
start_containers() {
    print_status "Starting containers..."
    docker-compose up -d
    
    print_status "Waiting for containers to be ready..."
    sleep 15
    
    # Check if containers are running
    if ! docker-compose ps | grep -q "Up"; then
        print_error "Containers failed to start properly"
        docker-compose logs
        exit 1
    fi
    
    print_status "Containers are running"
}

# Stop the containers
stop_containers() {
    print_status "Stopping containers..."
    docker-compose down
}

# Install test dependencies
install_test_deps() {
    print_status "Installing test dependencies..."
    pip install -r tests/requirements.txt
}

# Run tests
run_tests() {
    local test_type=$1
    
    case $test_type in
        "all")
            print_status "Running all tests..."
            pytest tests/ -v
            ;;
        "health")
            print_status "Running health tests..."
            pytest tests/test_health.py -v
            ;;
        "agents")
            print_status "Running agent tests..."
            pytest tests/test_agents.py -v
            ;;
        "database")
            print_status "Running database tests..."
            pytest tests/test_database.py -v
            ;;
        "docker")
            print_status "Running Docker tests..."
            pytest tests/test_docker_integration.py -v
            ;;
        "fast")
            print_status "Running fast tests (excluding slow tests)..."
            pytest tests/ -v -m "not slow"
            ;;
        *)
            print_error "Unknown test type: $test_type"
            echo "Available test types: all, health, agents, database, docker, fast"
            exit 1
            ;;
    esac
}

# Main execution
main() {
    local test_type=${1:-"all"}
    
    print_status "Starting test suite for agent-os-docker"
    
    # Check prerequisites
    check_docker
    check_docker_compose
    
    # Install test dependencies
    install_test_deps
    
    # Start containers
    start_containers
    
    # Run tests
    run_tests "$test_type"
    
    # Stop containers
    stop_containers
    
    print_status "Test suite completed"
}

# Handle script arguments
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $0 [test_type]"
    echo ""
    echo "Test types:"
    echo "  all      - Run all tests (default)"
    echo "  health   - Run only health check tests"
    echo "  agents   - Run only agent tests"
    echo "  database - Run only database tests"
    echo "  docker   - Run only Docker tests"
    echo "  fast     - Run fast tests (excluding slow tests)"
    echo ""
    echo "Examples:"
    echo "  $0              # Run all tests"
    echo "  $0 health       # Run only health tests"
    echo "  $0 fast         # Run fast tests only"
    exit 0
fi

# Run main function
main "$@" 