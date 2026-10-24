package local.batbridge;

import com.mythicscape.batclient.interfaces.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import javax.swing.SwingUtilities;

/**
 * Loopback-only, token-authenticated bridge between the BatMUD client and a
 * local agent process. No model or game credentials are loaded.
 *
 *   GET  /status                          connection and cursor state
 *   GET  /events?after&limit&wait_ms      incremental game output, oldest first
 *   POST /command                          one UTF-8 single-line command
 *
 * Each connection is served on its own daemon thread, so a long poll or a
 * slow command dispatch never blocks game callbacks or other requests.
 */
public final class AgentBridge extends BatClientPlugin implements BatClientPluginTrigger, BatClientPluginUtil {
    // The port override only exists so tests can run beside a live game client;
    // the shipped client always uses the default.
    private static final int PORT = Integer.getInteger("batbridge.port", 18765);
    private static final int CAPACITY = 2000;      // ring buffer of recent events
    private static final int DEFAULT_LIMIT = 500;  // events per /events response
    private static final int MAX_WAIT_MS = 10000;  // longest /events long poll
    // Command rate limit: burst of RATE_BURST commands, then one new token per
    // RATE_REFILL_MS. Rejected commands are NOT dispatched. Test overrides via
    // system properties; production defaults are 3 and 3000.
    private static final long RATE_BURST = Math.max(1, Long.getLong("batbridge.rate.burst", 3));
    private static final long RATE_REFILL_MS = Math.max(1, Long.getLong("batbridge.rate.refill_ms", 3000));
    private static final String VERSION = "0.3.0";

    private final Deque<String> events = new ArrayDeque<String>();
    private long seq = 0, commands = 0;
    private volatile boolean running = false;
    private volatile boolean shutdownRequested = false;
    private ServerSocket server;
    private ExecutorService pool;
    private String token;
    private Path auditLog;
    private double rateTokens = RATE_BURST;
    private long rateLastMs = System.currentTimeMillis();
    private final String session = UUID.randomUUID().toString();

    public String getName() { return "AgentBridge"; }

    public void loadPlugin() {
        // Excelsior JET can crash when a plugin touches the native Swing UI
        // while the splash screen is still being torn down. Defer all setup.
        Thread startup = new Thread(new Runnable() { public void run() {
            try { Thread.sleep(2500L); } catch (InterruptedException e) { return; }
            initialize();
        }}, "BatMUD-AgentBridge-startup");
        startup.setDaemon(true);
        startup.start();
    }

    private void initialize() {
        if (shutdownRequested) return; // clientExit() already ran during the startup delay
        try {
            Path dir = Paths.get(getBaseDirectory(), "agent-bridge");
            Files.createDirectories(dir);
            auditLog = dir.resolve("command-log.jsonl");
            Path key = dir.resolve("token.txt");
            if (Files.exists(key)) {
                token = new String(Files.readAllBytes(key), StandardCharsets.UTF_8).trim();
            } else {
                token = UUID.randomUUID().toString() + UUID.randomUUID().toString();
                Files.write(key, token.getBytes(StandardCharsets.UTF_8), StandardOpenOption.CREATE_NEW);
            }
            if (token.length() < 32) throw new IOException("Invalid bridge token");
            server = new ServerSocket();
            server.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), PORT));
            pool = Executors.newCachedThreadPool(new ThreadFactory() {
                public Thread newThread(Runnable r) {
                    Thread t = new Thread(r, "BatMUD-AgentBridge-worker");
                    t.setDaemon(true);
                    return t;
                }
            });
            running = true;
            Thread worker = new Thread(new Runnable() { public void run() { serve(); } }, "BatMUD-AgentBridge");
            worker.setDaemon(true);
            worker.start();
            SwingUtilities.invokeLater(new Runnable() { public void run() {
                if (running) getClientGUI().printText("generic",
                        "AgentBridge " + VERSION + " ready: 127.0.0.1:" + PORT + " (authenticated)\n", false);
            }});
        } catch (final Exception e) {
            clientExit();
            SwingUtilities.invokeLater(new Runnable() { public void run() {
                getClientGUI().printText("generic",
                        "AgentBridge startup failed: " + e.getClass().getSimpleName() + ": " + e.getMessage() + "\n", false);
            }});
        }
    }

    public ParsedResult trigger(ParsedResult input) {
        if (input != null && running) record(input.getStrippedText(), input.getOriginalText());
        return input;
    }

    private synchronized void record(String text, String raw) {
        long id = ++seq;
        events.addLast("{\"seq\":" + id + ",\"time_ms\":" + System.currentTimeMillis()
                + ",\"text\":" + quote(text) + ",\"raw\":" + quote(raw) + "}");
        while (events.size() > CAPACITY) events.removeFirst();
        notifyAll(); // wake long-polling /events readers
    }

    private synchronized String status() {
        return "{\"version\":" + quote(VERSION)
                + ",\"session\":" + quote(session)
                + ",\"connected\":" + getNet().isConnected()
                + ",\"latest_seq\":" + seq
                + ",\"oldest_seq\":" + (seq - events.size() + 1)
                + ",\"commands_sent\":" + commands
                + ",\"rate_burst\":" + RATE_BURST
                + ",\"rate_refill_ms\":" + RATE_REFILL_MS + "}";
    }

    /**
     * Waits up to waitMs for events past after, then returns one bounded
     * batch, oldest first. more=true means another batch is already waiting.
     */
    private synchronized String output(long after, int limit, long waitMs) throws InterruptedException {
        if (waitMs > 0) {
            long deadline = System.currentTimeMillis() + waitMs;
            while (running && seq <= after) {
                long left = deadline - System.currentTimeMillis();
                if (left <= 0) break;
                wait(left);
            }
        }
        long oldest = seq - events.size() + 1, id = oldest;
        int available = (int) Math.max(0, Math.min(seq - after, (long) events.size()));
        StringBuilder b = new StringBuilder();
        b.append("{\"session\":").append(quote(session))
                .append(",\"latest_seq\":").append(seq)
                .append(",\"oldest_seq\":").append(oldest)
                .append(",\"truncated\":").append(after < oldest - 1)
                .append(",\"more\":").append(available > limit)
                .append(",\"events\":[");
        boolean first = true;
        int taken = 0;
        for (String event : events) {
            if (id <= after) { id++; continue; }
            if (taken == limit) break;
            if (!first) b.append(',');
            first = false;
            b.append(event);
            taken++;
            id++;
        }
        return b.append("]}").toString();
    }

    private void serve() {
        while (running) {
            try {
                final Socket s = server.accept();
                pool.execute(new Runnable() { public void run() {
                    try {
                        s.setSoTimeout(3000);
                        handle(s);
                    } catch (Exception ignored) {
                        // A malformed or closed connection never stops game callbacks.
                    } finally {
                        try { s.close(); } catch (IOException ignored) {}
                    }
                }});
            } catch (Exception e) {
                if (running) {
                    try { Thread.sleep(100L); } catch (InterruptedException ie) { return; }
                }
                // else: clientExit() closed the socket; the loop exits on `running`
            }
        }
        if (pool != null) pool.shutdownNow();
    }

    private String line(InputStream in) throws IOException {
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        int c;
        while ((c = in.read()) != -1) {
            if (c == '\n') return new String(b.toByteArray(), StandardCharsets.US_ASCII).replace("\r", "");
            if (b.size() >= 8192) throw new IOException("Header too long");
            b.write(c);
        }
        throw new EOFException();
    }

    private void handle(Socket s) throws Exception {
        InputStream in = s.getInputStream();
        String[] request = line(in).split(" ");
        if (request.length != 3) { reply(s, 400, "{\"error\":\"invalid_request\"}"); return; }
        Map<String, String> headers = new HashMap<String, String>();
        for (int i = 0; ; i++) {
            String h = line(in);
            if (h.length() == 0) break;
            if (i >= 32) throw new IOException("Too many headers");
            int n = h.indexOf(':');
            if (n > 0) headers.put(h.substring(0, n).trim().toLowerCase(Locale.ROOT), h.substring(n + 1).trim());
        }
        String auth = headers.get("authorization");
        if (auth == null || !MessageDigest.isEqual(("Bearer " + token).getBytes(StandardCharsets.UTF_8),
                auth.getBytes(StandardCharsets.UTF_8))) {
            reply(s, 401, "{\"error\":\"unauthorized\"}"); return;
        }
        if (headers.containsKey("origin")) { reply(s, 403, "{\"error\":\"browser_origin_not_allowed\"}"); return; }
        URI uri = new URI(request[1]);
        String path = uri.getPath();
        if ("/status".equals(path)) {
            if (!"GET".equals(request[0])) { reply(s, 405, "{\"error\":\"method_not_allowed\"}"); return; }
            reply(s, 200, status()); return;
        }
        if ("/events".equals(path)) {
            if (!"GET".equals(request[0])) { reply(s, 405, "{\"error\":\"method_not_allowed\"}"); return; }
            long after = 0, waitMs = 0;
            int limit = DEFAULT_LIMIT;
            String q = uri.getRawQuery();
            if (q != null) {
                for (String pair : q.split("&")) {
                    int eq = pair.indexOf('=');
                    if (eq <= 0 || eq == pair.length() - 1) { reply(s, 400, "{\"error\":\"invalid_query\"}"); return; }
                    String k = pair.substring(0, eq), v = pair.substring(eq + 1);
                    if (!v.matches("[0-9]{1,18}")) { reply(s, 400, "{\"error\":\"invalid_query\"}"); return; }
                    long parsed = Long.parseLong(v);
                    if ("after".equals(k)) after = parsed;
                    else if ("limit".equals(k)) {
                        if (parsed < 1 || parsed > CAPACITY) { reply(s, 400, "{\"error\":\"invalid_query\"}"); return; }
                        limit = (int) parsed;
                    } else if ("wait_ms".equals(k)) {
                        if (parsed > MAX_WAIT_MS) { reply(s, 400, "{\"error\":\"invalid_query\"}"); return; }
                        waitMs = parsed;
                    } else { reply(s, 400, "{\"error\":\"invalid_query\"}"); return; }
                }
            }
            reply(s, 200, output(after, limit, waitMs)); return;
        }
        if ("/command".equals(path)) {
            if (!"POST".equals(request[0])) { reply(s, 405, "{\"error\":\"method_not_allowed\"}"); return; }
            String contentType = headers.get("content-type");
            // Guard against an agent accidentally dispatching a JSON body into the
            // game. x-www-form-urlencoded is allowed because curl -d and urllib
            // send it by default and its body is still the raw command text.
            if (contentType != null) {
                String ct = contentType.toLowerCase(Locale.ROOT);
                if (!ct.startsWith("text/") && !ct.startsWith("application/x-www-form-urlencoded")) {
                    reply(s, 415, "{\"error\":\"text_content_type_required\"}"); return;
                }
            }
            if (!getNet().isConnected()) { reply(s, 409, "{\"error\":\"not_connected\"}"); return; }
            int len;
            try { len = Integer.parseInt(headers.get("content-length")); }
            catch (Exception e) { reply(s, 411, "{\"error\":\"content_length_required\"}"); return; }
            if (len < 1 || len > 1024 || headers.containsKey("transfer-encoding")) { reply(s, 400, "{\"error\":\"invalid_length\"}"); return; }
            byte[] bytes = new byte[len];
            new DataInputStream(in).readFully(bytes);
            final String command = new String(bytes, StandardCharsets.UTF_8).trim();
            if (command.isEmpty() || command.length() > 500 || command.matches("(?s).*[\\x00-\\x1f\\x7f].*")) {
                reply(s, 400, "{\"error\":\"single_line_required\"}"); return;
            }
            // Rate limit BEFORE dispatch: a rejected command never reached the
            // game, so the client may safely retry after retry_after_ms.
            long retryMs = acquireRateToken();
            if (retryMs > 0) {
                reply(s, 429, "{\"error\":\"rate_limited\",\"dispatched\":false,\"retry_after_ms\":" + retryMs
                        + ",\"burst\":" + RATE_BURST + ",\"refill_ms\":" + RATE_REFILL_MS + "}",
                        "Retry-After: " + ((retryMs + 999) / 1000) + "\r\n");
                return;
            }
            final long before; synchronized (this) { before = seq; }
            FutureTask<Boolean> task = new FutureTask<Boolean>(new Callable<Boolean>() { public Boolean call() {
                if (!getNet().isConnected()) return false;
                getClientGUI().doCommand(command);
                synchronized (AgentBridge.this) { commands++; }
                return true;
            }});
            SwingUtilities.invokeLater(task);
            try {
                if (!task.get(5, TimeUnit.SECONDS)) { reply(s, 409, "{\"error\":\"disconnected_before_send\"}"); return; }
                audit(command, before);
                reply(s, 200, "{\"dispatched\":true,\"after_seq\":" + before + ",\"session\":" + quote(session) + "}");
            } catch (TimeoutException e) {
                task.cancel(false);
                reply(s, 504, "{\"error\":\"dispatch_timeout_outcome_unknown_do_not_retry_blindly\"}");
            } catch (InterruptedException e) {
                task.cancel(false);
                reply(s, 503, "{\"error\":\"shutting_down\"}");
            } catch (ExecutionException e) {
                reply(s, 500, "{\"error\":\"dispatch_failed\"}");
            }
            return;
        }
        reply(s, 404, "{\"error\":\"not_found\"}");
    }

    /**
     * Token bucket for /command. Returns 0 after consuming one token, or the
     * milliseconds to wait for the next token without consuming anything.
     */
    private synchronized long acquireRateToken() {
        long now = System.currentTimeMillis();
        rateTokens = Math.min((double) RATE_BURST, rateTokens + (double) (now - rateLastMs) / RATE_REFILL_MS);
        rateLastMs = now;
        if (rateTokens >= 1.0) { rateTokens -= 1.0; return 0; }
        return (long) Math.ceil((1.0 - rateTokens) * RATE_REFILL_MS);
    }

    /** Appends every dispatched command to command-log.jsonl for later replay. */
    private void audit(String command, long beforeSeq) {
        if (auditLog == null) return;
        String line = "{\"time_ms\":" + System.currentTimeMillis() + ",\"session\":" + quote(session)
                + ",\"command\":" + quote(command) + ",\"after_seq\":" + beforeSeq + "}\n";
        try {
            Files.write(auditLog, line.getBytes(StandardCharsets.UTF_8),
                    StandardOpenOption.CREATE, StandardOpenOption.APPEND);
        } catch (IOException ignored) {
            // Auditing must never break or delay a dispatch.
        }
    }

    private static String reason(int code) {
        switch (code) {
            case 200: return "OK";
            case 400: return "Bad Request";
            case 401: return "Unauthorized";
            case 403: return "Forbidden";
            case 404: return "Not Found";
            case 405: return "Method Not Allowed";
            case 409: return "Conflict";
            case 411: return "Length Required";
            case 415: return "Unsupported Media Type";
            case 429: return "Too Many Requests";
            case 503: return "Service Unavailable";
            case 504: return "Gateway Timeout";
            default: return "Error";
        }
    }

    private void reply(Socket s, int code, String json) throws IOException { reply(s, code, json, null); }

    private void reply(Socket s, int code, String json, String extraHeaders) throws IOException {
        byte[] body = json.getBytes(StandardCharsets.UTF_8);
        OutputStream out = s.getOutputStream();
        out.write(("HTTP/1.1 " + code + " " + reason(code)
                + "\r\nContent-Type: application/json; charset=utf-8\r\nCache-Control: no-store\r\nConnection: close\r\n"
                + (extraHeaders == null ? "" : extraHeaders)
                + "Content-Length: " + body.length + "\r\n\r\n").getBytes(StandardCharsets.US_ASCII));
        out.write(body);
        out.flush();
    }

    /** Minimal JSON string encoder; escapes control characters. */
    static String quote(String s) {
        if (s == null) return "null";
        StringBuilder b = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"': b.append("\\\""); break;
                case '\\': b.append("\\\\"); break;
                case '\n': b.append("\\n"); break;
                case '\r': b.append("\\r"); break;
                case '\t': b.append("\\t"); break;
                default: if (c < 32) b.append(String.format("\\u%04x", (int) c)); else b.append(c);
            }
        }
        return b.append('"').toString();
    }

    public synchronized void clientExit() {
        shutdownRequested = true;
        running = false;
        notifyAll(); // wake long-polling /events readers so they can finish
        try { if (server != null) server.close(); } catch (IOException ignored) {}
    }
}
