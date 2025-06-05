# Basic Agno A2A Agent Example

Basic Agno A2A Agent example that uses A2A to send and receive messages to/from an agent.

## Getting started

1. Clone a2a python repository: https://github.com/google/a2a-python

2. Install the a2a library in your virtual environment which has Agno installed

   ```bash
   pip install .
   ```

3. Start the server

   ```bash
   python cookbook/examples/a2a/basic_agent
   ```

4. Run the test client in a different terminal

   ```bash
   python cookbook/examples/a2a/basic_agent/client.py
   ```

## Notes

- The test client sends a message to the server and prints the response.
- The server uses the `BasicAgentExecutor` to execute the message and send the response back to the client.
- Streaming is not yet functional.
- The server runs on `http://localhost:9999` by default.
