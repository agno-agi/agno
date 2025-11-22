"""Railway resource types and installation order."""

# Railway resource types
RailwayResourceType = {
    "Project": "RailwayProject",
    "Environment": "RailwayEnvironment",
    "Service": "RailwayService",
    "Variable": "RailwayVariable",
    "VariableCollection": "RailwayVariableCollection",
}

# Installation order for Railway resources
# Lower numbers are installed first
# This ensures dependencies are created in the correct order:
# Project → Environment → Service (including Postgres) → Variables
RailwayResourceInstallOrder = {
    "RailwayProject": 100,
    "RailwayEnvironment": 200,
    "RailwayPostgres": 300,  # Database service (same as RailwayService)
    "RailwayService": 300,
    "RailwayVariable": 400,
    "RailwayVariableCollection": 400,  # Same as Variable
}
