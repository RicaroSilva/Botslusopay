/*
 * Anfitrião dos robôs Groovy do Bot Manager.
 *
 *   java -Djava.security.manager=allow -cp groovy.jar:groovy-json.jar groovy.ui.GroovyMain BmHost.groovy <modo>
 *
 * Modos: run (executa), check (só compila: erros de sintaxe e de segurança), ast (devolve a estrutura do código
 * em JSON, para a conversão Groovy → fluxo).
 *
 * Protocolo (uma mensagem JSON por linha):
 *   stdin  ← 1.ª linha: {"code": ..., "variables": {...}, "params": {...}, "run_id": ..., "out_dir": ...}
 *            seguintes: respostas {"id": n, "ok": true, "value": ...} | {"id": n, "ok": false, "error": "..."}
 *   stdout → "@@CALL {"id": n, "op": ..., "args": {...}}", "@@LOG {"level": ..., "msg": ...}", "@@END {...}"
 *
 * O código do robô nunca recebe credenciais: http/email/sql são executados pelo motor do Bot Manager (Python),
 * que valida hosts, aplica as credenciais do cofre e regista tudo. Isolamento (defesa em profundidade):
 * verificação do código antes de compilar (sem anotações, imports, classes e métodos perigosos) e um
 * SecurityManager que impede processos, ligações de rede e acesso a ficheiros fora da pasta da execução.
 */

import groovy.json.JsonSlurper
import groovy.transform.Field
import org.codehaus.groovy.ast.*
import org.codehaus.groovy.ast.expr.*
import org.codehaus.groovy.ast.stmt.*
import org.codehaus.groovy.classgen.GeneratorContext
import org.codehaus.groovy.control.*
import org.codehaus.groovy.control.customizers.CompilationCustomizer
import org.codehaus.groovy.control.messages.ExceptionMessage
import org.codehaus.groovy.control.messages.SyntaxErrorMessage
import org.codehaus.groovy.syntax.SyntaxException

import java.security.Permission
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

// ------------------------------------------------------------------------------------------- erros

class RoboFalhou extends RuntimeException {
    RoboFalhou(String m) { super(m) }
}

/** terminar(): é um Error para não ser apanhado por "catch (e)" no código do robô (como o "Terminar" dos fluxos). */
class RoboTerminou extends Error {
    RoboTerminou(String m) { super(m) }
}

class CodigoRecusado extends RuntimeException {
    int line
    CodigoRecusado(String m, int line) { super(m); this.line = line }
}

// ------------------------------------------------------------------------------------------- JSON

/** JSON com os mesmos separadores do Python (json.dumps), para o texto ser igual ao dos fluxos. */
class Json {
    static String dump(Object v) {
        StringBuilder sb = new StringBuilder()
        write(sb, v)
        return sb.toString()
    }

    private static void write(StringBuilder sb, Object v) {
        if (v == null) { sb.append("null"); return }
        if (v instanceof Boolean) { sb.append(v ? "true" : "false"); return }
        if (v instanceof Number) { sb.append(Helpers.numText((Number) v)); return }
        if (v instanceof Map) {
            sb.append("{")
            boolean first = true
            ((Map) v).each { k, x ->
                if (!first) sb.append(", ")
                first = false
                str(sb, String.valueOf(k)); sb.append(": "); write(sb, x)
            }
            sb.append("}")
            return
        }
        if (v instanceof Collection || v instanceof Object[]) {
            sb.append("[")
            boolean first = true
            (v as List).each { x ->
                if (!first) sb.append(", ")
                first = false
                write(sb, x)
            }
            sb.append("]")
            return
        }
        if (v instanceof java.time.temporal.TemporalAccessor) { str(sb, Helpers.isoText(v)); return }
        str(sb, v.toString())
    }

    private static void str(StringBuilder sb, String s) {
        sb.append('"')
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"': sb.append('\\"'); break
                case '\\': sb.append('\\\\'); break
                case '\n': sb.append('\\n'); break
                case '\r': sb.append('\\r'); break
                case '\t': sb.append('\\t'); break
                default:
                    if (c < 0x20) sb.append(String.format('\\u%04x', (int) c)) else sb.append(c)
            }
        }
        sb.append('"')
    }

    static Object parse(String s) {
        return s == null || s.trim().isEmpty() ? null : new JsonSlurper().parseText(s)
    }
}

// ------------------------------------------------------------------------------------------- ponte

class Bridge {
    static PrintStream out
    static final Map<Long, CompletableFuture<Object>> pending = new ConcurrentHashMap<>()
    static final AtomicLong ids = new AtomicLong()
    static long maxCalls = 500000
    static Thread reader
    static Runnable onClose

    static void start(BufferedReader inp) {
        reader = new Thread({
            String line
            while ((line = inp.readLine()) != null) {
                def r = new JsonSlurper().parseText(line)
                def f = pending.remove(((Number) r.id).longValue())
                if (f == null) continue
                if (r.ok) f.complete(r.value) else f.completeExceptionally(new RoboFalhou(String.valueOf(r.error)))
            }
            pending.values().each { it.completeExceptionally(new RoboFalhou("ligação ao motor perdida")) }
            if (onClose != null) onClose.run()  // o motor terminou: a JVM não pode ficar órfã
        } as Runnable, 'bm-ponte')
        reader.daemon = true
        reader.start()
    }

    static Object call(String op, Map args) {
        long id = ids.incrementAndGet()
        if (id > maxCalls) throw new RoboFalhou("limite de ${maxCalls} operações excedido")
        def f = new CompletableFuture<Object>()
        pending[id] = f
        send("@@CALL " + Json.dump([id: id, op: op, args: args]))
        try {
            return f.get()
        } catch (java.util.concurrent.ExecutionException e) {
            throw e.cause
        }
    }

    static synchronized void send(String line) {
        out.println(line)
        out.flush()
    }

    static void log(String level, Object msg) {
        send("@@LOG " + Json.dump([level: level, msg: Helpers.text(msg)]))
    }
}

/** println do robô vai para o log da execução (o stdout real é o canal do protocolo). */
class LogStream extends OutputStream {
    private final ByteArrayOutputStream buf = new ByteArrayOutputStream()

    synchronized void write(int b) {
        if (b == ('\n' as char)) flushLine() else buf.write(b)
        if (buf.size() > 16000) flushLine()
    }

    private void flushLine() {
        String s = buf.toString("UTF-8").replaceAll(/\r$/, "")
        buf.reset()
        Bridge.log("INFO", s)
    }
}

// ------------------------------------------------------------------------------------------- API

class Http {
    private Object req(String method, String url, Object corpo, Map opts) {
        Map a = [method: method, url: Helpers.text(url)]
        if (corpo != null) a.body = (corpo instanceof CharSequence) ? [text: corpo.toString()] : [json: corpo]
        (opts ?: [:]).each { k, v -> a[String.valueOf(k)] = v instanceof CharSequence ? v.toString() : v }
        return Bridge.call("http", a)
    }

    Object get(Map opts = [:], String url) { req("GET", url, null, opts) }
    Object delete(Map opts = [:], String url) { req("DELETE", url, null, opts) }
    Object post(Map opts = [:], String url, Object corpo = null) { req("POST", url, corpo, opts) }
    Object put(Map opts = [:], String url, Object corpo = null) { req("PUT", url, corpo, opts) }
    Object patch(Map opts = [:], String url, Object corpo = null) { req("PATCH", url, corpo, opts) }
}

class Email {
    void enviar(Map opts) {
        Map a = [:]
        opts.each { k, v -> a[String.valueOf(k)] = v instanceof CharSequence ? v.toString() : v }
        Bridge.call("email", a)
    }
}

class Sql {
    List consultar(String credencial, String query, Map params = [:]) {
        return (List) Bridge.call("sql", [credencial: credencial, query: query, params: params ?: [:], escrita: false])
    }

    List executar(String credencial, String query, Map params = [:]) {
        return (List) Bridge.call("sql", [credencial: credencial, query: query, params: params ?: [:], escrita: true])
    }
}

class Ficheiro {
    String ler(String nome) { (String) Bridge.call("file_read", [nome: nome]) }
    void gravar(String nome, Object texto) { Bridge.call("file_write", [nome: nome, texto: Helpers.text(texto), acrescentar: false]) }
    void acrescentar(String nome, Object texto) { Bridge.call("file_write", [nome: nome, texto: Helpers.text(texto), acrescentar: true]) }
    boolean existe(String nome) { (boolean) Bridge.call("file_exists", [nome: nome]) }
    void csv(Map opts = [:], String nome, List linhas) { Bridge.call("file_csv", [nome: nome, linhas: linhas, colunas: opts.colunas, separador: opts.separador ?: ";"]) }
}

// ------------------------------------------------------------------------------------------- funções auxiliares

/** Mesma semântica dos filtros dos fluxos (lusopay_worker.flowengine), para as conversões serem fiéis. */
class Helpers {
    static String numText(Number n) {
        if (n instanceof BigDecimal) {
            BigDecimal b = ((BigDecimal) n).stripTrailingZeros()
            return b.scale() <= 0 ? b.toBigInteger().toString() + (((BigDecimal) n).scale() > 0 ? ".0" : "") : b.toPlainString()
        }
        if (n instanceof Double || n instanceof Float) {
            double d = n.doubleValue()
            return d == Math.rint(d) && !Double.isInfinite(d) ? String.valueOf((long) d) + ".0" : String.valueOf(d)
        }
        return n.toString()
    }

    static String isoText(Object v) {
        if (v instanceof java.time.LocalDateTime) {
            def d = (java.time.LocalDateTime) v
            return d.nano == 0 ? d.format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss")) : d.toString()
        }
        return v.toString()
    }

    static String text(Object v) {
        if (v == null) return ""
        if (v instanceof Map || v instanceof Collection) return Json.dump(v)
        if (v instanceof Boolean) return v ? "True" : "False"
        if (v instanceof Number) return numText((Number) v)
        if (v instanceof java.time.LocalDateTime) return ((java.time.LocalDateTime) v).toString().replace('T', ' ')
        return v.toString()
    }

    static Object parsejson(Object v) {
        if (v instanceof CharSequence) return Json.parse(v.toString())
        return v
    }

    static List as_list(Object v) {
        if (v == null) return []
        if (v instanceof List) return (List) v
        if (v instanceof CharSequence) {
            String t = v.toString()
            if (t.trim().isEmpty()) return []
            def p
            try { p = new JsonSlurper().parseText(t) } catch (Exception ignored) { return [t] }
            return p instanceof List ? (List) p : [p]
        }
        if (v instanceof Collection) return new ArrayList((Collection) v)
        return [v]
    }

    static Number num(Object v) {
        if (v instanceof Boolean) return v ? 1 : 0
        BigDecimal n
        if (v instanceof Number) {
            n = new BigDecimal(v.toString())
        } else {
            String t = text(v).trim().replace(" ", "")
            if (t.isEmpty()) return 0
            try { n = new BigDecimal(t) } catch (NumberFormatException ignored) {
                n = new BigDecimal(t.replace(".", "").replace(",", "."))
            }
        }
        if (n.signum() == 0 || n.stripTrailingZeros().scale() <= 0) return n.toBigInteger().longValueExact()
        return n
    }

    static boolean is_numeric(Object v) {
        String t = text(v).trim()
        if (t.isEmpty()) return false
        try { Double.parseDouble(t.replace(",", ".")); return true } catch (NumberFormatException ignored) { return false }
    }

    private static int nth(String t, String sub, int skip) {
        int idx = -1
        for (int i = 0; i <= skip; i++) {
            idx = t.indexOf(sub, idx + 1)
            if (idx < 0) return -1
        }
        return idx
    }

    static String between(Object v, Object lead, Object trail, Object skip = 0) {
        String t = text(v), l = text(lead), r = text(trail)
        int i = nth(t, l, num(skip) as int)
        if (i < 0) return ""
        int start = i + l.length()
        int j = r ? t.indexOf(r, start) : t.length()
        return j < 0 ? t.substring(start) : t.substring(start, j)
    }

    static String after(Object v, Object lead, Object skip = 0) {
        String t = text(v), l = text(lead)
        int i = nth(t, l, num(skip) as int)
        return i < 0 ? "" : t.substring(i + l.length())
    }

    static String before(Object v, Object trail, Object skip = 0) {
        String t = text(v), r = text(trail)
        int i = nth(t, r, num(skip) as int)
        return i < 0 ? t : t.substring(0, i)
    }

    static String regex(Object v, String pattern, Object group = 0) {
        def m = (text(v) =~ pattern)
        if (!m.find()) return ""
        return m.group(num(group) as int) ?: ""
    }

    static String regex_replace(Object v, String pattern, Object replacement = "") {
        String r = text(replacement).replace('\\', '\\\\').replaceAll(/\$\{(\w+)\}|\$(\d+)/) { all, name, n -> '\\$' + (name ?: n) }
        r = r.replaceAll(/\\\$(\w+)/) { all, g -> '\\$' + (g.isNumber() ? g : "{$g}") }
        return text(v).replaceAll(pattern, r.replace('\\$', '$'))
    }

    static List regex_split(Object v, String pattern) {
        return text(v).split(pattern, -1) as List
    }

    static List split_text(Object v, Object sep) {
        String t = text(v).replace("\r\n", "\n")
        String s = text(sep).replace("\r\n", "\n")
        List out = []
        int pos = 0, i
        while ((i = t.indexOf(s, pos)) >= 0 && s) { out << t.substring(pos, i); pos = i + s.length() }
        out << t.substring(pos)
        return out
    }

    static Object find(Object data, String key) {
        if (data instanceof Map) {
            if (((Map) data).containsKey(key)) return ((Map) data)[key]
            for (x in ((Map) data).values()) { def f = find(x, key); if (f != null) return f }
        } else if (data instanceof List) {
            for (x in (List) data) { def f = find(x, key); if (f != null) return f }
        }
        return null
    }

    static Object jsonpath(Object v, String path) {
        def data = parsejson(v)
        path = path.trim()
        if (path.contains("[?")) throw new RoboFalhou("JSONPath com filtro não suportado: $path")
        if (path.startsWith('$..')) {
            String rest = path.substring(3)
            int dot = rest.indexOf('.')
            String key = dot < 0 ? rest : rest.substring(0, dot)
            def found = find(data, key)
            return dot < 0 ? found : extract(found, rest.substring(dot + 1))
        }
        return extract(data, path)
    }

    static Object extract(Object data, String path) {
        path = path.startsWith('$.') ? path.substring(2) : path.replaceAll(/^\$+/, "")
        List toks = (path =~ /[^.\[\]]+|\[\*\]|\[\d+\]/).collect { it }
        return walk(data, toks)
    }

    private static Object walk(Object cur, List toks) {
        for (int i = 0; i < toks.size(); i++) {
            String t = toks[i]
            if (t == "[*]") {
                if (!(cur instanceof List)) return null
                return ((List) cur).collect { walk(it, toks.subList(i + 1, toks.size())) }
            }
            if (t.startsWith("[")) {
                int idx = t[1..-2] as int
                cur = (cur instanceof List && idx < ((List) cur).size()) ? ((List) cur)[idx] : null
            } else {
                cur = cur instanceof Map ? ((Map) cur)[t] : null
            }
            if (cur == null) return null
        }
        return cur
    }

    static java.time.LocalDateTime todate(Object v) {
        if (v instanceof java.time.LocalDateTime) return (java.time.LocalDateTime) v
        if (v instanceof java.time.LocalDate) return ((java.time.LocalDate) v).atStartOfDay()
        String s = text(v).trim()
        if (s.length() == 10) return java.time.LocalDate.parse(s).atStartOfDay()
        return java.time.LocalDateTime.parse(s.replace(' ', 'T'))
    }

    static String date(Object v, String fmt = '%Y-%m-%d') {
        def d = todate(v)
        StringBuilder sb = new StringBuilder()
        for (int i = 0; i < fmt.length(); i++) {
            char c = fmt.charAt(i)
            if (c != ('%' as char) || i + 1 >= fmt.length()) { sb.append(c); continue }
            char f = fmt.charAt(++i)
            switch (f) {
                case 'Y': sb.append(String.format('%04d', d.year)); break
                case 'y': sb.append(String.format('%02d', d.year % 100)); break
                case 'm': sb.append(String.format('%02d', d.monthValue)); break
                case 'd': sb.append(String.format('%02d', d.dayOfMonth)); break
                case 'H': sb.append(String.format('%02d', d.hour)); break
                case 'M': sb.append(String.format('%02d', d.minute)); break
                case 'S': sb.append(String.format('%02d', d.second)); break
                case 'j': sb.append(String.format('%03d', d.dayOfYear)); break
                case 'B': sb.append(d.month.getDisplayName(java.time.format.TextStyle.FULL, Locale.ENGLISH)); break
                case 'b': sb.append(d.month.getDisplayName(java.time.format.TextStyle.SHORT, Locale.ENGLISH)); break
                case 'A': sb.append(d.dayOfWeek.getDisplayName(java.time.format.TextStyle.FULL, Locale.ENGLISH)); break
                case 'a': sb.append(d.dayOfWeek.getDisplayName(java.time.format.TextStyle.SHORT, Locale.ENGLISH)); break
                case '%': sb.append('%'); break
                default: sb.append('%').append(f)
            }
        }
        return sb.toString()
    }

    static java.time.LocalDateTime add_days(Object v, Object n) { todate(v).plusDays(num(n) as long) }

    static java.time.LocalDateTime add_time(Object v, String unit, Object n) {
        def d = todate(v)
        unit = unit.toLowerCase()
        def k = num(n)
        if (unit.startsWith("second")) return d.plusNanos((long) (k.doubleValue() * 1e9))
        if (unit.startsWith("minute")) return d.plusSeconds((long) (k.doubleValue() * 60))
        if (unit.startsWith("hour")) return d.plusSeconds((long) (k.doubleValue() * 3600))
        if (unit.startsWith("day")) return d.plusSeconds((long) (k.doubleValue() * 86400))
        if (unit.startsWith("month")) return d.plusMonths(k.longValue())
        if (unit.startsWith("year")) return d.plusMonths(k.longValue() * 12)
        throw new RoboFalhou("unidade de tempo desconhecida: $unit")
    }

    static java.time.LocalDateTime now() { java.time.LocalDateTime.now().withNano(java.time.LocalDateTime.now().nano.intdiv(1000) * 1000) }

    static java.time.LocalDateTime today() { java.time.LocalDate.now().atStartOfDay() }

    static java.time.LocalDateTime first_day_of_month(Object offset = 0) {
        return java.time.LocalDate.now().withDayOfMonth(1).plusMonths(num(offset) as long).atStartOfDay()
    }

    static String money(Object v) { String.format(Locale.ROOT, '%.2f', num(v).doubleValue()).replace('.', ',') }

    static String decimal(Object v, Object n = 2) { String.format(Locale.ROOT, "%.${num(n)}f", num(v).doubleValue()).replace('.', ',') }

    static String tojson(Object v) { Json.dump(v) }

    static Object fromjson(Object v) { Json.parse(text(v)) }

    static List sample(Object v, Object n) {
        List l = new ArrayList(as_list(v))
        Collections.shuffle(l)
        return l.take(Math.min(num(n) as int, l.size()))
    }

    static List row_values(Object v) { v instanceof Map ? new ArrayList(((Map) v).values()) : as_list(v) }

    static int length(Object v) {
        if (v == null) return 0
        if (v instanceof Map) return ((Map) v).size()
        if (v instanceof Collection) return ((Collection) v).size()
        return text(v).length()
    }

    static boolean taskt_compare(Object a, String op, Object b, boolean cs = false, String mode = "text") {
        op = op.trim().toLowerCase()
        def x, y
        if (mode == "date") {
            x = todate(text(a).trim()); y = todate(text(b).trim())
        } else {
            x = text(a); y = text(b)
            if (op in ["contains", "does not contain", "is equal to", "is not equal to"] && !cs) { x = x.toLowerCase(); y = y.toLowerCase() }
            if (op in ["is greater than", "is greater than or equal to", "is less than", "is less than or equal to"]) {
                x = num(x); y = num(y)
            } else if (op in ["is equal to", "is not equal to"] && is_numeric(x) && is_numeric(y)) {
                x = num(x); y = num(y)
            }
        }
        switch (op) {
            case "is equal to": return x == y
            case "is not equal to": return x != y
            case "is greater than": return x > y
            case "is greater than or equal to": return x >= y
            case "is less than": return x < y
            case "is less than or equal to": return x <= y
            case "contains": return ((String) x).contains((String) y)
            case "does not contain": return !((String) x).contains((String) y)
        }
        throw new RoboFalhou("operador desconhecido: $op")
    }
}

/** Classe base dos robôs: funções disponíveis diretamente no código. */
abstract class RoboBase extends Script {
    void log(Object msg) { Bridge.log("INFO", msg) }
    void aviso(Object msg) { Bridge.log("WARNING", msg) }
    void erro(Object msg) { Bridge.log("ERROR", msg) }
    void falhar(Object msg) { throw new RoboFalhou(Helpers.text(msg)) }
    void terminar(Object msg = "") { throw new RoboTerminou(Helpers.text(msg)) }

    /** Executa `acao` para cada elemento, até `n` em simultâneo (as chamadas http/sql/email correm em paralelo). */
    void paralelo(Collection itens, int n, Closure acao) {
        if (n <= 1) { itens.each(acao); return }
        def pool = java.util.concurrent.Executors.newFixedThreadPool(Math.min(n, 20))
        try {
            def futures = itens.collect { item -> pool.submit({ acao.call(item) } as java.util.concurrent.Callable) }
            futures.each { f ->
                try { f.get() } catch (java.util.concurrent.ExecutionException e) { throw e.cause }
            }
        } finally {
            pool.shutdownNow()
        }
    }

    static String text(Object v) { Helpers.text(v) }
    static Number num(Object v) { Helpers.num(v) }
    static Object parsejson(Object v) { Helpers.parsejson(v) }
    static List as_list(Object v) { Helpers.as_list(v) }
    static Object jsonpath(Object v, String p) { Helpers.jsonpath(v, p) }
    static String regex(Object v, String p, Object g = 0) { Helpers.regex(v, p, g) }
    static String regex_replace(Object v, String p, Object r = "") { Helpers.regex_replace(v, p, r) }
    static List regex_split(Object v, String p) { Helpers.regex_split(v, p) }
    static List split_text(Object v, Object s) { Helpers.split_text(v, s) }
    static String between(Object v, Object l, Object t, Object s = 0) { Helpers.between(v, l, t, s) }
    static String after(Object v, Object l, Object s = 0) { Helpers.after(v, l, s) }
    static String before(Object v, Object t, Object s = 0) { Helpers.before(v, t, s) }
    static String date(Object v, String f = '%Y-%m-%d') { Helpers.date(v, f) }
    static java.time.LocalDateTime add_days(Object v, Object n) { Helpers.add_days(v, n) }
    static java.time.LocalDateTime add_time(Object v, String u, Object n) { Helpers.add_time(v, u, n) }
    static java.time.LocalDateTime todate(Object v) { Helpers.todate(v) }
    static java.time.LocalDateTime now() { Helpers.now() }
    static java.time.LocalDateTime today() { Helpers.today() }
    static java.time.LocalDateTime first_day_of_month(Object o = 0) { Helpers.first_day_of_month(o) }
    static String money(Object v) { Helpers.money(v) }
    static String decimal(Object v, Object n = 2) { Helpers.decimal(v, n) }
    static String tojson(Object v) { Helpers.tojson(v) }
    static Object fromjson(Object v) { Helpers.fromjson(v) }
    static Object find(Object v, String k) { Helpers.find(v, k) }
    static List sample(Object v, Object n) { Helpers.sample(v, n) }
    static List row_values(Object v) { Helpers.row_values(v) }
    static int length(Object v) { Helpers.length(v) }
    static Object extrair(Object v, String caminho) { Helpers.extract(Helpers.parsejson(v), caminho) }
    static boolean contem(Object onde, Object o) {
        if (onde == null) return false
        if (onde instanceof Map) return ((Map) onde).containsKey(o)
        if (onde instanceof Collection) return ((Collection) onde).contains(o)
        return Helpers.text(onde).contains(Helpers.text(o))
    }
    static boolean is_numeric(Object v) { Helpers.is_numeric(v) }
    static boolean taskt_compare(Object a, String op, Object b, boolean cs = false, String mode = "text") {
        Helpers.taskt_compare(a, op, b, cs, mode)
    }
    boolean file_exists(Object nome) { ((Ficheiro) getBinding().getVariable("ficheiro")).existe(Helpers.text(nome)) }
}

// ------------------------------------------------------------------------------------------- verificação do código

/** Recusa construções perigosas antes de compilar (fase CONVERSION, antes de qualquer transformação AST). */
class Verificador extends CompilationCustomizer {
    static final Set<String> NOMES_PROIBIDOS = ['File', 'Files', 'Path', 'Paths', 'FileSystems', 'Runtime', 'Process',
        'ProcessBuilder', 'System', 'Thread', 'ThreadGroup', 'ClassLoader', 'GroovyShell', 'GroovyClassLoader', 'Eval',
        'Socket', 'ServerSocket', 'DatagramSocket', 'URL', 'URI', 'URLConnection', 'HttpURLConnection', 'HttpClient',
        'Class', 'Method', 'Field', 'Constructor', 'Unsafe', 'SecurityManager', 'MethodHandles', 'ScriptEngineManager',
        'FileInputStream', 'FileOutputStream', 'FileReader', 'FileWriter', 'RandomAccessFile', 'ObjectInputStream',
        'InetAddress', 'Executors', 'ForkJoinPool', 'Grape', 'Sql', 'Bridge', 'Helpers', 'Verificador', 'Seguranca'] as Set
    static final Set<String> METODOS_PROIBIDOS = ['execute', 'getClass', 'forName', 'newInstance', 'invokeMethod',
        'getMetaClass', 'setMetaClass', 'getProperty', 'setProperty', 'evaluate', 'exit', 'halt', 'getRuntime',
        'getDeclaredField', 'getDeclaredFields', 'getDeclaredMethod', 'getDeclaredMethods', 'getDeclaredConstructor',
        'setAccessible', 'loadClass', 'defineClass', 'getClassLoader', 'consumeProcessOutput', 'waitForProcessOutput',
        'withObjectInputStream', 'withObjectOutputStream', 'mixin', 'getBinding', 'setBinding', 'run', 'sleep',
        'getenv', 'getProperties', 'setOut', 'setErr', 'setIn', 'load', 'loadLibrary', 'getField', 'getMethod',
        'getMethods', 'getFields', 'invoke', 'asType', 'with', 'tap', 'identity', 'getAt', 'putAt'] as Set
    static final Set<String> PROPRIEDADES_PROIBIDAS = ['class', 'metaClass', 'classLoader', 'binding', 'declaredFields',
        'declaredMethods', 'theUnsafe', 'protectionDomain', 'out', 'err'] as Set
    static final List<String> IMPORTS_PERMITIDOS = ['java.util.', 'java.time.', 'java.math.', 'java.text.',
        'groovy.json.JsonSlurper', 'groovy.json.JsonOutput']

    Verificador() { super(CompilePhase.CONVERSION) }

    void call(SourceUnit source, GeneratorContext context, ClassNode classNode) {
        ModuleNode m = source.AST
        if (m.package != null) recusar("declaração 'package' não permitida", m.package.lineNumber)
        (m.imports + m.starImports + m.staticImports.values() + m.staticStarImports.values()).each { ImportNode i ->
            if (!i.annotations.isEmpty()) recusar("anotações não permitidas", i.lineNumber)
            String nome = i.className ?: i.packageName ?: ""
            if (i.isStatic() || !IMPORTS_PERMITIDOS.any { p -> nome.startsWith(p) || (p.endsWith('.') && (nome + '.').startsWith(p)) })
                recusar("import não permitido: ${i.text}", i.lineNumber)
        }
        def visitor = new CodeVisitorSupport() {
            void visitMethodCallExpression(MethodCallExpression e) {
                if (!(e.method instanceof ConstantExpression)) recusar("nome de método dinâmico não permitido", e.lineNumber)
                if (e.methodAsString in METODOS_PROIBIDOS) recusar("método não permitido: ${e.methodAsString}", e.lineNumber)
                super.visitMethodCallExpression(e)
            }
            void visitStaticMethodCallExpression(StaticMethodCallExpression e) {
                if (e.method in METODOS_PROIBIDOS) recusar("método não permitido: ${e.method}", e.lineNumber)
                super.visitStaticMethodCallExpression(e)
            }
            void visitPropertyExpression(PropertyExpression e) {
                if (!(e.property instanceof ConstantExpression)) recusar("propriedade dinâmica não permitida", e.lineNumber)
                if (e.propertyAsString in PROPRIEDADES_PROIBIDAS) recusar("propriedade não permitida: ${e.propertyAsString}", e.lineNumber)
                super.visitPropertyExpression(e)
            }
            void visitAttributeExpression(AttributeExpression e) { recusar("acesso direto a atributos (.@) não permitido", e.lineNumber) }
            void visitMethodPointerExpression(MethodPointerExpression e) { recusar("ponteiros de método (.&) não permitidos", e.lineNumber) }
            void visitMethodReferenceExpression(MethodReferenceExpression e) { recusar("referências de método (::) não permitidas", e.lineNumber) }
            void visitConstructorCallExpression(ConstructorCallExpression e) {
                verificarTipo(e.type, e.lineNumber)
                super.visitConstructorCallExpression(e)
            }
            void visitClassExpression(ClassExpression e) { verificarTipo(e.type, e.lineNumber) }
            void visitVariableExpression(VariableExpression e) {
                if (e.name in NOMES_PROIBIDOS) recusar("não permitido: ${e.name}", e.lineNumber)
            }
            void visitCastExpression(CastExpression e) {
                verificarTipo(e.type, e.lineNumber)
                super.visitCastExpression(e)
            }
            void visitDeclarationExpression(DeclarationExpression e) {
                if (!e.annotations.isEmpty()) recusar("anotações não permitidas", e.lineNumber)
                verificarTipo(e.leftExpression.type, e.lineNumber)
                super.visitDeclarationExpression(e)
            }
            void visitClosureExpression(ClosureExpression e) {
                e.parameters?.each { verificarTipo(it.type, e.lineNumber) }
                super.visitClosureExpression(e)
            }
        }
        List<ClassNode> classes = m.classes
        classes.each { ClassNode c ->
            // a única anotação aceite é a @BaseScript que a configuração põe na classe do script
            if (c.annotations.any { !(c.script && it.classNode.name == "groovy.transform.BaseScript") })
                recusar("anotações não permitidas", c.lineNumber)
            if (c != m.scriptClassDummy && !c.script) {
                verificarTipo(c.superClass, c.lineNumber)
                c.interfaces.each { verificarTipo(it, c.lineNumber) }
            }
            c.fields.each { FieldNode f ->
                if (!f.annotations.isEmpty()) recusar("anotações não permitidas", f.lineNumber)
                verificarTipo(f.type, f.lineNumber)
                f.initialExpression?.visit(visitor)
            }
            c.properties.each { PropertyNode p -> if (!p.annotations.isEmpty()) recusar("anotações não permitidas", p.lineNumber) }
            (c.methods + c.declaredConstructors).each { MethodNode mn ->
                if (mn.lineNumber < 1) return  // gerado pelo compilador (o código do script é verificado abaixo)
                if (!mn.annotations.isEmpty() && !mn.annotations.every { it.classNode.name in ['Override'] })
                    recusar("anotações não permitidas", mn.lineNumber)
                mn.parameters.each { if (!it.annotations.isEmpty()) recusar("anotações não permitidas", mn.lineNumber); verificarTipo(it.type, mn.lineNumber) }
                verificarTipo(mn.returnType, mn.lineNumber)
                mn.code?.visit(visitor)
            }
            c.objectInitializerStatements.each { it.visit(visitor) }
        }
        m.statementBlock.visit(visitor)
    }

    static void verificarTipo(ClassNode t, int linha) {
        if (t == null) return
        String nome = t.name
        String simples = nome.contains('.') ? nome.substring(nome.lastIndexOf('.') + 1) : nome
        if (simples in NOMES_PROIBIDOS || nome.startsWith("java.io.") || nome.startsWith("java.nio.") ||
                nome.startsWith("java.net.") || nome.startsWith("java.lang.reflect.") || nome.startsWith("java.lang.invoke.") ||
                nome.startsWith("sun.") || nome.startsWith("jdk.") || nome.startsWith("org.codehaus.groovy.") ||
                nome.startsWith("groovy.lang.Groovy") || nome.startsWith("javax.script."))
            recusar("tipo não permitido: ${nome}", linha)
        t.genericsTypes?.each { verificarTipo(it.type, linha) }
    }

    static void recusar(String msg, int linha) { throw new CodigoRecusado(msg, linha) }
}

// ------------------------------------------------------------------------------------------- SecurityManager

@groovy.transform.CompileStatic
class Seguranca extends SecurityManager {
    private final List<String> leitura
    private final List<String> escrita
    private final ThreadLocal<Boolean> aVerificar = new ThreadLocal<Boolean>()
    volatile boolean ativo = true

    Seguranca(List<String> leitura, List<String> escrita) {
        this.leitura = new ArrayList<String>()
        for (String p : leitura) this.leitura.add(canonico(p))
        this.escrita = new ArrayList<String>()
        for (String p : escrita) this.escrita.add(canonico(p))
    }

    private static String canonico(String p) {
        try {
            return java.nio.file.Paths.get(p).toAbsolutePath().normalize().toString()
        } catch (Exception ignored) {
            return p
        }
    }

    private static boolean dentro(String path, List<String> raizes) {
        if (path == "<<ALL FILES>>") return false
        String c = canonico(path)
        for (String r : raizes) {
            if (c == r || c.startsWith(r + File.separator)) return true
        }
        return false
    }

    @Override
    void checkPermission(Permission p) {
        if (!ativo || aVerificar.get() == Boolean.TRUE) return
        aVerificar.set(Boolean.TRUE)
        try {
            verificar(p)
        } finally {
            aVerificar.remove()
        }
    }

    private void verificar(Permission p) {
        if (p instanceof RuntimePermission) {
            String n = p.getName()
            if (n == "setSecurityManager" || n.startsWith("exitVM") || n == "setIO" || n.startsWith("loadLibrary")
                    || n == "setFactory" || n.startsWith("defineClassInPackage.java"))
                throw new SecurityException("operação não permitida: " + n)
        } else if (p instanceof FilePermission) {
            String a = p.getActions()
            if (a.contains("execute")) throw new SecurityException("executar programas não é permitido")
            if (a.contains("write") || a.contains("delete")) {
                if (!dentro(p.getName(), escrita)) throw new SecurityException("escrita fora da pasta da execução: " + p.getName())
            } else if (a.contains("read")) {
                if (!dentro(p.getName(), leitura) && !dentro(p.getName(), escrita))
                    throw new SecurityException("leitura não permitida: " + p.getName())
            }
        } else if (p instanceof java.net.SocketPermission) {
            throw new SecurityException("ligações de rede diretas não são permitidas: use http.get/post")
        } else if (p instanceof java.net.NetPermission || p instanceof java.net.URLPermission) {
            throw new SecurityException("rede não permitida")
        }
    }

    @Override
    void checkPermission(Permission p, Object ctx) { checkPermission(p) }
}

// ------------------------------------------------------------------------------------------- AST → JSON (conversão)

class AstJson {
    static Map stmt(Statement s) {
        Map n = [line: s.lineNumber, col: s.columnNumber, lastLine: s.lastLineNumber, lastCol: s.lastColumnNumber]
        switch (s) {
            case BlockStatement: return n + [k: "block", body: s.statements.collect { stmt(it) }]
            case ExpressionStatement: return n + [k: "expr", expr: expr(s.expression)]
            case IfStatement:
                return n + [k: "if", cond: expr(s.booleanExpression.expression), then: stmt(s.ifBlock),
                            else: s.elseBlock instanceof EmptyStatement ? null : stmt(s.elseBlock)]
            case ForStatement:
                if (s.variable == ForStatement.FOR_LOOP_DUMMY) return n + [k: "unsupported", what: "ciclo for clássico"]
                return n + [k: "for", var: s.variable.name, coll: expr(s.collectionExpression), body: stmt(s.loopBlock)]
            case WhileStatement: return n + [k: "while", cond: expr(s.booleanExpression.expression), body: stmt(s.loopBlock)]
            case TryCatchStatement:
                return n + [k: "try", body: stmt(s.tryStatement),
                            catches: s.catchStatements.collect { [var: it.variable.name, body: stmt(it.code)] },
                            finally: s.finallyStatement instanceof EmptyStatement ? null : stmt(s.finallyStatement)]
            case BreakStatement: return n + [k: "break"]
            case ContinueStatement: return n + [k: "continue"]
            case ReturnStatement: return n + [k: "return", expr: s.returnExpression instanceof ConstantExpression && s.returnExpression.value == null ? null : expr(s.returnExpression)]
            case EmptyStatement: return n + [k: "empty"]
            case ThrowStatement: return n + [k: "throw", expr: expr(s.expression)]
            default: return n + [k: "unsupported", what: s.class.simpleName]
        }
    }

    static Map expr(Expression e) {
        Map n = [line: e.lineNumber, col: e.columnNumber, lastLine: e.lastLineNumber, lastCol: e.lastColumnNumber]
        switch (e) {
            case DeclarationExpression:
                if (!(e.leftExpression instanceof VariableExpression)) return n + [k: "unsupported", what: "declaração múltipla"]
                return n + [k: "assign", target: [k: "var", name: e.leftExpression.name], value: expr(e.rightExpression), decl: true]
            case BinaryExpression:
                String op = e.operation.text
                if (op == "=") return n + [k: "assign", target: expr(e.leftExpression), value: expr(e.rightExpression)]
                if (op == "[") return n + [k: "index", obj: expr(e.leftExpression), index: expr(e.rightExpression)]
                if (op in ["+=", "-=", "*=", "/="])
                    return n + [k: "assign", target: expr(e.leftExpression), value: n + [k: "bin", op: op[0], left: expr(e.leftExpression), right: expr(e.rightExpression)]]
                return n + [k: "bin", op: op, left: expr(e.leftExpression), right: expr(e.rightExpression)]
            case ConstantExpression: return n + [k: "const", value: e.value instanceof Number ? e.value.toString() : e.value, type: e.value == null ? "null" : e.value.class.simpleName]
            case VariableExpression: return n + [k: "var", name: e.name]
            case GStringExpression: return n + [k: "gstring", strings: e.strings.collect { it.value }, values: e.values.collect { expr(it) }]
            case MethodCallExpression:
                return n + [k: "call", obj: e.implicitThis ? null : expr(e.objectExpression), method: e.methodAsString,
                            safe: e.safe, args: args(e.arguments)]
            case StaticMethodCallExpression: return n + [k: "call", obj: null, method: e.method, args: args(e.arguments)]
            case PropertyExpression: return n + [k: "prop", obj: expr(e.objectExpression), prop: e.propertyAsString, safe: e.safe]
            case ListExpression: return n + [k: "list", items: e.expressions.collect { expr(it) }]
            case MapExpression: return n + [k: "map", entries: e.mapEntryExpressions.collect { [key: expr(it.keyExpression), value: expr(it.valueExpression)] }]
            case NotExpression: return n + [k: "not", expr: expr(e.expression)]
            case BooleanExpression: return expr(e.expression)
            case ElvisOperatorExpression: return n + [k: "elvis", left: expr(e.trueExpression), right: expr(e.falseExpression)]
            case TernaryExpression: return n + [k: "ternary", cond: expr(e.booleanExpression.expression), then: expr(e.trueExpression), else: expr(e.falseExpression)]
            case UnaryMinusExpression: return n + [k: "neg", expr: expr(e.expression)]
            case RangeExpression: return n + [k: "range", from: expr(e.from), to: expr(e.to), inclusive: e.inclusive]
            case CastExpression: return n + [k: "cast", type: e.type.name, expr: expr(e.expression)]
            case PostfixExpression: return n + [k: "incdec", op: e.operation.text, expr: expr(e.expression)]
            case PrefixExpression: return n + [k: "incdec", op: e.operation.text, expr: expr(e.expression)]
            case ClosureExpression: return n + [k: "closure", params: (e.parameters ?: []).collect { it.name }, body: stmt(e.code)]
            case TupleExpression: return n + [k: "tuple", items: e.expressions.collect { expr(it) }]
            default: return n + [k: "unsupported", what: e.class.simpleName]
        }
    }

    static List args(Expression a) {
        if (a instanceof TupleExpression) {
            List out = []
            a.expressions.each { x ->
                if (x instanceof NamedArgumentListExpression)
                    out << ([k: "named", entries: x.mapEntryExpressions.collect { [key: expr(it.keyExpression), value: expr(it.valueExpression)] }])
                else out << expr(x)
            }
            return out
        }
        return [expr(a)]
    }
}

// ------------------------------------------------------------------------------------------- principal

@Field PrintStream PROTO = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8")

String modo = args ? args[0] : "run"
BufferedReader entrada = new BufferedReader(new InputStreamReader(System.in, "UTF-8"))
Map init = (Map) new JsonSlurper().parseText(entrada.readLine())
String codigo = (String) init.code
Bridge.out = PROTO

void fim(Map r) {
    PROTO.println("@@END " + Json.dump(r))
    PROTO.flush()
}

Map erroCompilacao(Throwable t) {
    List erros = []
    if (t instanceof MultipleCompilationErrorsException) {
        t.errorCollector.errors.each { msg ->
            if (msg instanceof SyntaxErrorMessage) {
                SyntaxException c = msg.cause
                erros << [line: c.line, col: c.startColumn, message: c.originalMessage]
            } else if (msg instanceof ExceptionMessage) {
                def c = msg.cause
                erros << [line: c instanceof CodigoRecusado ? c.line : 0, col: 0, message: c.message]
            } else {
                erros << [line: 0, col: 0, message: msg.toString()]
            }
        }
    } else if (t instanceof CodigoRecusado) {
        erros << [line: t.line, col: 0, message: t.message]
    } else {
        erros << [line: 0, col: 0, message: t.toString()]
    }
    return [status: "error", errors: erros]
}

int linhaDoRobo(Throwable t) {
    for (Throwable c = t; c != null; c = c.cause) {
        def el = c.stackTrace.find { it.fileName == "Robo.groovy" && it.lineNumber > 0 }
        if (el) return el.lineNumber
    }
    return 0
}

CompilerConfiguration conf = new CompilerConfiguration()
conf.scriptBaseClass = RoboBase.name
conf.addCompilationCustomizers(new Verificador())
conf.sourceEncoding = "UTF-8"

String outDir = init.out_dir ? (String) init.out_dir : System.getProperty("java.io.tmpdir")
List<String> leitura = [System.getProperty("java.home"), System.getProperty("bm.host.dir") ?: ""]
leitura += (System.getProperty("java.class.path") ?: "").split(File.pathSeparator).collect { new File(it).parent ?: it }
leitura += ["/dev/random", "/dev/urandom", "/proc/self", "/sys/fs/cgroup", "/etc/localtime", "/usr/share/zoneinfo"]
List<String> escrita = [outDir, System.getProperty("java.io.tmpdir")]

if (modo == "ast") {
    try {
        CompilationUnit cu = new CompilationUnit(conf)
        cu.addSource("Robo.groovy", codigo)
        cu.compile(Phases.CONVERSION)
        ModuleNode m = cu.AST.modules[0]
        List metodos = m.methods.collect { [name: it.name, line: it.lineNumber] }
        List classes = m.classes.findAll { !it.script }.collect { [name: it.name, line: it.lineNumber] }
        fim([status: "ok", body: AstJson.stmt(m.statementBlock), methods: metodos, classes: classes])
    } catch (Throwable t) {
        fim(erroCompilacao(t))
    }
    return
}

// o println do robô vai para o log (o stdout real fica reservado ao protocolo)
System.setOut(new PrintStream(new LogStream(), true, "UTF-8"))

// a partir daqui o código do robô é compilado e executado com o SecurityManager ativo
Seguranca sm = new Seguranca(leitura.findAll { it }, escrita)
try {
    System.setSecurityManager(sm)
} catch (UnsupportedOperationException e) {
    if (System.getenv("BM_GROOVY_SEM_ISOLAMENTO") != "1") {
        fim([status: "error", errors: [[line: 0, col: 0, message: "Esta versão do Java não permite isolar o robô (SecurityManager). Instale o Java 21."]]])
        return
    }
}

GroovyShell shell
Script script
try {
    Binding binding = new Binding()
    shell = new GroovyShell(this.class.classLoader, binding, conf)
    script = shell.parse(codigo, "Robo.groovy")
} catch (Throwable t) {
    fim(erroCompilacao(t))
    sm.ativo = false
    Runtime.runtime.halt(0)
}
if (modo == "check") {
    fim([status: "ok"])
    sm.ativo = false
    Runtime.runtime.halt(0)
}

Bridge.onClose = { sm.ativo = false; Runtime.runtime.halt(3) } as Runnable
Bridge.start(entrada)
Binding b = script.binding
((Map) (init.variables ?: [:])).each { k, v -> b.setVariable((String) k, v) }
b.setVariable("params", init.params ?: [:])
b.setVariable("run_id", init.run_id)
b.setVariable("http", new Http())
b.setVariable("email", new Email())
b.setVariable("sql", new Sql())
b.setVariable("ficheiro", new Ficheiro())
try {
    script.run()
    fim([status: "ok"])
} catch (RoboTerminou t) {
    fim([status: "stop", message: t.message])
} catch (RoboFalhou t) {
    fim([status: "fail", message: t.message, line: linhaDoRobo(t)])
} catch (SecurityException t) {
    fim([status: "fail", message: "bloqueado: " + t.message, line: linhaDoRobo(t)])
} catch (StackOverflowError t) {
    fim([status: "fail", message: "recursão infinita (StackOverflowError)", line: linhaDoRobo(t)])
} catch (OutOfMemoryError t) {
    fim([status: "fail", message: "memória esgotada", line: 0])
} catch (Throwable t) {
    String msg = t.class.simpleName + ": " + (t.message ?: "")
    fim([status: "fail", message: msg, line: linhaDoRobo(t)])
}
sm.ativo = false
Runtime.runtime.halt(0)
