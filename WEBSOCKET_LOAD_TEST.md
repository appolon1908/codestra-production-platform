# WebSocket Load Test

Controlled synthetic staging load used 250 distinct server-bound agents over the public WSS route. Results from the final post-proxy-restart run:

- authenticated sockets: 250
- connect duration: 3.559 seconds
- targeted delivery latency: 12.477 ms
- screen-pop delivery latency: 17.802 ms
- adjacent-agent delivery: none
- CPU/memory: remained within configured 1 CPU / 256 MiB gateway limits; no OOM or restart

`LOAD_TEST=PASS`  
`P95_DELIVERY_LATENCY=PASS`

