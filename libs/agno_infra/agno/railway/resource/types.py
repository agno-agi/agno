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
# Project → Environment → Service → Variables
RailwayResourceInstallOrder = {
    "RailwayProject": 100,
    "RailwayEnvironment": 200,
    "RailwayService": 300,
    "RailwayVariable": 400,
    "RailwayVariableCollection": 400,  # Same as Variable
}
