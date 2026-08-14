# EtherCAT Analyzer Agent Result

## Task
Find the ET1100 Auto Increment Addressing behavior.

## Routing
- Selected docs:

- Selected source:
- Capture mode: tool_agent

## Result
Based on the ET1100 specification excerpts, Auto Increment Addressing is a device addressing mode where the slave is addressed via a Device Position Address. When an Auto Increment Read (APRD) command is received, the slave increments its internal address after processing the command. The specification notes that the slave puts read data into the EtherCAT datagram if the received address matches. This mode is distinct from Configured Station Address and Broadcast modes. The exact increment step size (e.g., 1 byte, 2 bytes) and the specific address register behavior are not explicitly detailed in the provided excerpts, only that the address is incremented.
