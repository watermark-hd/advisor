#!/usr/bin/perl
# claude-agent.pl (advisor) — 古いIntel Mac (Snow Leopard 〜 High Sierra 世代)
# 向けの自己完結型 AIエージェント。外部CPANモジュールに依存しない。
# Anthropic (Claude) と Google (Gemini) の両APIに対応。
#
# Mavericks(10.9)以降(Tier B)は標準のcurlが既にTLS1.2対応のため、追加の
# ビルドなしでそのまま動く。Snow Leopard〜Mountain Lion(Tier A, 10.6-10.8)
# では ppc_claude_cli と同じ手順でOpenSSL/curlをソースからビルドし、
# CLAUDE_CURL / CLAUDE_CACERT でその場所を指定する。
#
# 使い方:
#   export ANTHROPIC_API_KEY=sk-ant-...      # または GEMINI_API_KEY=...
#   export CLAUDE_PROVIDER=anthropic          # または gemini
#   perl claude-agent.pl

use strict;
use warnings;
use utf8;  # このファイル自身に書かれた日本語リテラルをUTF-8として解釈する
use Encode qw(decode FB_DEFAULT);

# 画面出力は明示的にUTF-8として扱う。
binmode STDOUT, ':encoding(UTF-8)';
binmode STDERR, ':encoding(UTF-8)';

# STDINはあえて生バイトのまま(:encoding層を付けない)にしておく。
# Perl 5.8.6のPerlIO :encoding(UTF-8) は、実際のキーボード入力のように
# バイトが少しずつ届く対話的な読み込みだと、マルチバイト文字の途中で
# 読み込みバッファが分割されてしまい "utf8 does not map to Unicode" と
# いう文字化けエラーを起こすことがある(パイプ経由の一括入力では再現
# しない)。そのため、行を読み終えてバイト列が全部揃った後にまとめて
# デコードする(下のwhileループ内)方式にしている。

# :encoding層を付けるとSTDOUTの自動フラッシュが効かなくなり、プロンプトの
# 表示がAPI応答まで遅延して見えることがあるため、明示的に毎回flushする。
$| = 1;

# 端末設定を起動時に控えておき、どんな終わり方をしても必ず元に戻す。
# read_line_interactive は端末を raw モードにするので、途中で die すると
# 端末が壊れたまま(入力が見えない・改行されない)になってしまう。
# --- ログ2種 ---
# blog(): 常時ONの「パンくず」ログ。会話の中身は書かず、動作の節目と
#   終了理由だけを ~/.claude-agent/session.log に残す(起動時に消す)。
#   次に落ちたとき、環境変数の設定なしで最後の様子が分かるように。
# dbg():  CLAUDE_DEBUG_LOG=<path> のときだけ動く詳細ログ。APIの生の
#   やり取りまで書く。
my $BLOG_PATH = ($ENV{HOME} || '.') . '/.claude-agent/session.log';
{
    my $d = ($ENV{HOME} || '.') . '/.claude-agent';
    mkdir($d, 0700) unless -d $d;
    if (open(my $fh, '>', $BLOG_PATH)) { print $fh ''; close $fh; chmod 0600, $BLOG_PATH; }
}
sub _logline {
    my ($path, $msg) = @_;
    return unless $path;
    if (open(my $fh, '>>:encoding(UTF-8)', $path)) {
        my @t = localtime;
        printf $fh "[%02d:%02d:%02d] %s\n", $t[2], $t[1], $t[0], $msg;
        close $fh;
    }
}
sub blog { _logline($BLOG_PATH, join('', @_)); }
sub dbg  {
    my $line = join('', @_);
    blog(substr($line, 0, 200)) if $line !~ /^BODY:/;       # 本文以外は節目としてパンくずにも
    _logline($ENV{CLAUDE_DEBUG_LOG}, $line) if $ENV{CLAUDE_DEBUG_LOG};
}

# perl の警告(Deep recursion / Out of memory / uninitialized など)も
# 残す。無限ループやメモリ枯渇の手前が見えることがある。
$SIG{__WARN__} = sub { my $w = shift; blog("WARN: $w"); dbg("WARN: $w"); warn $w; };

blog("=== advisor start (pid $$) ===");

# 端末設定を起動時に控えておき、どんな終わり方をしても必ず元に戻す。
# read_line_interactive は端末を raw モードにするので、途中で die すると
# 端末が壊れたまま(入力が見えない・改行されない)になってしまう。
our $ORIG_STTY = `stty -g 2>/dev/null`;
chomp $ORIG_STTY;
sub restore_tty { system('stty', $ORIG_STTY) if $ORIG_STTY ne ''; }
END { blog("END reached (exit=$?)"); restore_tty(); }
$SIG{INT}  = sub { blog("SIGINT");  restore_tty(); print "\n中断しました。\n"; exit 130; };
$SIG{TERM} = sub { blog("SIGTERM"); restore_tty(); exit 143; };
$SIG{HUP}  = sub { blog("SIGHUP (端末が閉じられた?)"); restore_tty(); exit 129; };
$SIG{__DIE__} = sub { blog("DIE" . ($^S ? "(in eval)" : "(FATAL)") . ": " . substr($_[0],0,300)); return; };

# ------------------------------------------------------------------
# コマンドライン引数 (--help / --version はAPIキー無しでも動作させる)
# モデル切り替えは ~/bin/claude (シェルラッパー) 側の -m/--select-model で
# 行い、ここではCLAUDE_MODEL環境変数を読むだけにして本体は単純に保つ。
# ------------------------------------------------------------------
my $LIST_HISTORY   = 0;   # --list-history: 保存済みの会話を一覧表示して終了
my $RESUME         = 0;   # --resume: 保存済みの会話を選んで続きから再開
my $CHANGE_PASS    = 0;   # --change-passphrase: 履歴パスフレーズを変更して終了
my $SET_RECOVERY   = 0;   # --set-recovery: 合言葉(復旧用の秘密の質問)を設定して終了
my $GUI            = 0;   # --gui: 端末用の表示をやめ、1行1件のJSONで入出力する
                          #        (Python/tkinter のGUIから裏で駆動するため)

for my $arg (@ARGV) {
    if ($arg eq '--help' || $arg eq '-h') {
        print_help();
        exit 0;
    }
    if ($arg eq '--version') {
        print "advisor (high_sierra_claude) 0.1\n";
        exit 0;
    }
    if ($arg eq '--list-history')      { $LIST_HISTORY = 1; }
    if ($arg eq '--resume')            { $RESUME = 1; }
    if ($arg eq '--change-passphrase') { $CHANGE_PASS = 1; }
    if ($arg eq '--set-recovery')      { $SET_RECOVERY = 1; }
    if ($arg eq '--gui')               { $GUI = 1; }
}

sub print_help {
    print <<'EOH';
使い方: advisor [オプション]

  -h, --help            このヘルプを表示
      --version         バージョンを表示
      --list-history    保存済みの会話を一覧表示して終了
      --resume          保存済みの会話を選んで続きから再開
      --change-passphrase 履歴パスフレーズを変更して終了
      --set-recovery    合言葉(復旧用の秘密の質問)を設定して終了

環境変数:
  CLAUDE_PROVIDER    使うAI: anthropic (既定) または gemini
  ANTHROPIC_API_KEY  Anthropic APIキー (CLAUDE_PROVIDER=anthropic のとき必須)
  GEMINI_API_KEY     Gemini APIキー   (CLAUDE_PROVIDER=gemini のとき必須)
  CLAUDE_MODEL       使用するモデル (既定: claude-sonnet-5 / gemini-3.5-flash-lite)
  CLAUDE_GEMINI_THINKING  high にすると Gemini の思考を深くする (既定 low=速い)
  CLAUDE_CURL        curlコマンドのパス (既定: curl。PATH上のものを使用)
  CLAUDE_CACERT      CA証明書ファイル (既定: 未指定。システムcurlの信頼ストアを使用)
  CLAUDE_NO_HISTORY  1にすると会話を保存しない(パスフレーズも尋ねない)
  CLAUDE_OPENSSL     opensslコマンドのパス (既定: openssl)

会話中に /claude・/gemini でAIを切り替えられる(会話は引き継がれる)。
モデルの選択は `advisor --select-model` / `advisor -m <ID>` (シェルラッパー側)。
EOH
}

# ------------------------------------------------------------------
# 設定
# ------------------------------------------------------------------
my $CURL       = $ENV{CLAUDE_CURL} || 'curl';
my $CACERT     = $ENV{CLAUDE_CACERT} || '';
my $MAX_TOKENS = 4096;
# setup.sh を介さず、会話中の /claude・/gemini で入力したキーを保存する先。
my $ENV_FILE_PATH = ($ENV{HOME} || '.') . '/.claude-agent-env';

# プロバイダ切り替え。CLAUDE_PROVIDER=gemini でクレジットカード登録不要の
# Gemini API 無料枠を、既定(anthropic)では従量課金の Claude を使う。
# 会話中に /claude・/gemini でも切り替えられる(下の会話ループ参照)。
my ($PROVIDER, $API_KEY, $MODEL, $API_URL, $ANTHROPIC_VERSION);

# $provider に応じて $API_KEY / $MODEL / $API_URL 等を(再)設定する。
# 起動時と、会話中の /claude・/gemini の両方から呼ばれる。対応する
# 環境変数(ANTHROPIC_API_KEY / GEMINI_API_KEY)が無ければ die する
# — 起動時はそれで終了、切り替え時は呼び出し側で eval して握り、
# 今のプロバイダのまま継続する。
sub configure_provider {
    my ($provider) = @_;
    # CLAUDE_MODEL はプロバイダをまたぐと食い違うので、その provider の
    # 名前で始まるときだけ採用し、そうでなければ既定モデルにする。
    my $env_model = $ENV{CLAUDE_MODEL} || '';
    if ($provider eq 'gemini') {
        $ENV{GEMINI_API_KEY} or die "GEMINI_API_KEY を設定してください\n";
        $API_KEY = $ENV{GEMINI_API_KEY};
        $MODEL   = ($env_model =~ /^gemini/) ? $env_model : 'gemini-3.5-flash-lite';
        $API_URL = "https://generativelanguage.googleapis.com/v1beta/models/$MODEL:generateContent";
    }
    elsif ($provider eq 'anthropic') {
        $ENV{ANTHROPIC_API_KEY} or die "ANTHROPIC_API_KEY を設定してください\n";
        $API_KEY = $ENV{ANTHROPIC_API_KEY};
        $MODEL   = ($env_model =~ /^claude/) ? $env_model : 'claude-sonnet-5';
        $API_URL = 'https://api.anthropic.com/v1/messages';
        $ANTHROPIC_VERSION = '2023-06-01';
    }
    else {
        die "不明なプロバイダ: '$provider' (anthropic か gemini)\n";
    }
    $PROVIDER = $provider;
}

# 選べるAIの一覧 ([id, 説明], ...)。ラッパーが CLAUDE_MODELS_FILE で場所を教える。
my @MODEL_CHOICES;
if ($ENV{CLAUDE_MODELS_FILE} && open(my $mf, '<:encoding(UTF-8)', $ENV{CLAUDE_MODELS_FILE})) {
    while (my $l = <$mf>) {
        chomp $l;
        next unless $l =~ /\S/;
        my ($id, $desc) = split /\|/, $l, 2;
        push @MODEL_CHOICES, [ $id, (defined $desc && $desc ne '') ? $desc : $id ];
    }
    close $mf;
}

# ~/.claude-agent-env の1行を差し替える(無ければ追記)。会話中の切り替えを
# 次回起動にも引き継ぐため。
sub persist_env {
    my ($var, $val) = @_;
    return unless $ENV_FILE_PATH;
    my @lines;
    if (open(my $in, '<', $ENV_FILE_PATH)) {
        while (my $l = <$in>) {
            push @lines, $l unless $l =~ /^export \Q$var\E=/;
        }
        close $in;
    }
    push @lines, "export $var=$val\n";
    if (open(my $out, '>', $ENV_FILE_PATH)) {
        print $out @lines;
        close $out;
        chmod 0600, $ENV_FILE_PATH;
    }
}

# 会話中にプロバイダ(Claude/Gemini)を切り替える。キーが無ければその場で
# 入力してもらい、任意で保存する。成功したら 1、中止/失敗なら 0。
sub switch_provider {
    my ($target) = @_;
    eval { configure_provider($target) };
    return 1 unless $@;   # キーが揃っていてそのまま切り替えOK

    my $key_name = $target eq 'gemini' ? 'GEMINI_API_KEY' : 'ANTHROPIC_API_KEY';

    # GUI モードでは、その場でのキー入力はまだ用意していない。
    # setup.sh で登録してもらう。
    if ($GUI) {
        emit_error("$key_name が未登録です。setup.sh でそのAIのキーを登録してください。");
        return 0;
    }

    my $key = read_secret("\n$key_name が未設定です。貼り付けてEnter(空Enterでキャンセル): ");
    if (!defined $key || $key eq '') {
        print "キャンセルしました。[$PROVIDER / $MODEL] のままです。\n";
        return 0;
    }
    $ENV{$key_name} = $key;
    eval { configure_provider($target) };
    if ($@) { print "それでも切り替えられませんでした: $@"; return 0; }
    print "このキーを $ENV_FILE_PATH に保存しますか? [y/N] ";
    my $yn = <STDIN>;
    if (defined $yn && $yn =~ /^y/i) {
        persist_env($key_name, $key);
        print "保存しました。\n";
    }
    return 1;
}

# 選べるAIの一覧を番号付きで表示する
sub show_model_menu {
    unless (@MODEL_CHOICES) {
        print "\n(モデル一覧が読み込めません)\n";
        return;
    }
    print "\n";
    my $i = 1;
    for my $c (@MODEL_CHOICES) {
        my $mark = ($c->[0] eq $MODEL) ? ' ← 使用中' : '';
        printf "  %d) %s%s\n", $i++, $c->[1], $mark;
    }
    print "番号を入力すると切り替わります。そのまま質問してもOK。\n";
}

# 指定したモデルIDに切り替える。必要ならプロバイダも一緒に切り替え、
# 次回起動に引き継ぐため ~/.claude-agent-env にも書く。
sub switch_to_model {
    my ($id) = @_;
    my $target_provider = ($id =~ /^gemini/) ? 'gemini' : 'anthropic';
    my $prev_model = $ENV{CLAUDE_MODEL};
    $ENV{CLAUDE_MODEL} = $id;

    my $ok = 1;
    if ($target_provider ne $PROVIDER) {
        $ok = switch_provider($target_provider);
    }
    else {
        eval { configure_provider($PROVIDER) };  # $MODEL と(Geminiの)$API_URL を作り直す
        if ($@) { print $@; $ok = 0; }
    }

    unless ($ok) {
        # 切り替え失敗。元のモデルに戻す。
        if (defined $prev_model) { $ENV{CLAUDE_MODEL} = $prev_model } else { delete $ENV{CLAUDE_MODEL} }
        eval { configure_provider($PROVIDER) };
        return;
    }

    persist_env('CLAUDE_MODEL', $MODEL);
    persist_env('CLAUDE_PROVIDER', $PROVIDER);
    emit_note("→ [$PROVIDER / $MODEL] にしました。");
    gui_send({ t => 'model', provider => $PROVIDER, model => $MODEL }) if $GUI;
}

configure_provider($ENV{CLAUDE_PROVIDER} || 'anthropic');

# ------------------------------------------------------------------
# 出力の抽象化。端末モードでは今まで通り print、GUI モード($GUI)では
# 1行1件の JSON を STDOUT に書く。会話ループや run_tool はどちらか
# 意識しない。GUI 側 (Python/tkinter) がこの JSON を読んで画面を作る。
# ------------------------------------------------------------------
sub gui_send {
    my ($obj) = @_;
    print MiniJSON::encode($obj), "\n";
}
# GUI からの1行(JSON)を読んでデコード。EOF は undef、それ以外は必ずハッシュ参照。
sub gui_read {
    my $line = <STDIN>;
    return undef unless defined $line;
    $line =~ s/\r?\n\z//;
    my $text = decode('UTF-8', $line, FB_DEFAULT);
    my $obj  = eval { MiniJSON::decode($text) };
    return (ref $obj eq 'HASH') ? $obj : {};
}

sub emit_text {
    my ($text) = @_;
    if ($GUI) { gui_send({ t => 'text', text => $text }); }
    else      { print "\n$PROVIDER> $text\n"; }
}
sub emit_tool {
    my ($name, $input) = @_;
    if ($GUI) { gui_send({ t => 'tool', name => $name, input => $input }); }
    else      { print "\n[tool_use] $name(" . MiniJSON::encode($input) . ")\n"; }
}
sub emit_status {
    my ($text) = @_;
    if ($GUI) { gui_send({ t => 'status', text => $text }); }
    elsif ($text ne '') { print "\n... $text\n"; }
}
sub emit_error {
    my ($text) = @_;
    if ($GUI) { gui_send({ t => 'error', text => $text }); }
    else      { print "\n$text"; }
}
sub emit_note {   # 補助的なお知らせ(切り替え完了など)
    my ($text) = @_;
    if ($GUI) { gui_send({ t => 'note', text => $text }); }
    else      { print "\n$text\n"; }
}

# --- 会話履歴(暗号化してローカル保存) ---
# ランダムなマスター鍵で履歴ファイルを暗号化し、そのマスター鍵自体を
# パスフレーズ(と、任意で「合言葉」)で包んで保存する。どちらか一方で
# マスター鍵を取り出せるので、パスフレーズを忘れても合言葉で復旧できる。
my $HISTORY_ENABLED = $ENV{CLAUDE_NO_HISTORY} ? 0 : 1;
my $HISTORY_DIR     = "$ENV{HOME}/.claude-agent/history";
my $KEY_FILE        = "$HISTORY_DIR/key.enc";           # マスター鍵をパスフレーズで包んだもの
my $KEY_RECOVERY    = "$HISTORY_DIR/key.recovery.enc";  # 同じマスター鍵を合言葉の答えで包んだもの(任意)
my $KEY_RECOVERY_Q  = "$HISTORY_DIR/key.recovery.q";    # 合言葉の質問文(平文)
my $HISTORY_CHECK   = "$HISTORY_DIR/.check";            # 旧形式。存在すればマスター鍵方式へ移行する
my $OPENSSL         = $ENV{CLAUDE_OPENSSL} || 'openssl';
my $STARTED         = _timestamp();
my $SESSION_FILE;                                       # この会話の保存先(unlock後に決定)

my $SYSTEM_PROMPT = <<'EOS';
You are a lightweight coding assistant running in the terminal of an
older Intel Mac (High Sierra era) that's being kept useful instead of
thrown away. Many users here are not programmers; they want you to build
small personal tools for them. You have four tools: read_file,
write_file, list_dir, and run_shell. Use them to read/write files and
run commands in the user's working directory. Keep replies concise, and
always reply in the same language the user wrote in.

write_file and run_shell each ask the user for a y/n confirmation before
running. If a call comes back cancelled, it only means the user declined
THAT ONE action right then (often they were still typing a thought, or
want a change first) — it does NOT mean the environment blocks tools.
Never conclude that file writes or commands are disabled. Instead, stop,
say plainly what you were about to do, ask what they want to adjust, and
try again once they're ready. Do not silently retry the same write.

Before a multi-step build, tell the user in one or two lines what files
you'll create and what you'll run, so the confirmation prompts make sense.

Environment: `python3` is Python 3.10 (in the user's PATH via
~/.bash_profile; from run_shell use `python3` and it resolves). tkinter
is available. For extra libraries use `python3 -m pip install --user
<pkg>`. Prefer the standard library when it's enough.
EOS

# ------------------------------------------------------------------
# 最小限のJSONエンコーダ/デコーダ (依存ゼロ、Claude APIのメッセージ
# 構造に必要な範囲をカバーする再帰下降パーサー)
# ------------------------------------------------------------------
package MiniJSON;

sub encode {
    my ($v) = @_;
    my $r = ref $v;
    if ($r eq 'HASH') {
        return '{' . join(',', map {
            encode_string($_) . ':' . encode($v->{$_})
        } sort keys %$v) . '}';
    } elsif ($r eq 'ARRAY') {
        return '[' . join(',', map { encode($_) } @$v) . ']';
    } elsif (!defined $v) {
        return 'null';
    } elsif ($r eq 'SCALAR') {
        return $$v ? 'true' : 'false';
    } elsif ($v =~ /^-?\d+(\.\d+)?([eE][+-]?\d+)?$/) {
        return $v;
    } else {
        return encode_string($v);
    }
}

sub encode_string {
    my ($s) = @_;
    $s =~ s/([\\"])/\\$1/g;
    $s =~ s/\n/\\n/g;
    $s =~ s/\r/\\r/g;
    $s =~ s/\t/\\t/g;
    $s =~ s/([\x00-\x1f])/sprintf('\\u%04x', ord($1))/ge;
    return '"' . $s . '"';
}

# decode: 文字列 -> Perlデータ構造。posを進めながら解析する。
sub decode {
    my ($text) = @_;
    my $pos = 0;
    my $val = _decode_value(\$text, \$pos);
    return $val;
}

sub _skip_ws {
    my ($t, $p) = @_;
    $$p++ while $$p < length($$t) && substr($$t, $$p, 1) =~ /[\s]/;
}

sub _decode_value {
    my ($t, $p) = @_;
    _skip_ws($t, $p);
    my $c = substr($$t, $$p, 1);
    if ($c eq '{') { return _decode_object($t, $p); }
    if ($c eq '[') { return _decode_array($t, $p); }
    if ($c eq '"') { return _decode_string($t, $p); }
    if (substr($$t, $$p, 4) eq 'true') { $$p += 4; return 1; }
    if (substr($$t, $$p, 5) eq 'false') { $$p += 5; return 0; }
    if (substr($$t, $$p, 4) eq 'null') { $$p += 4; return undef; }
    # number
    if (substr($$t, $$p) =~ /^(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/) {
        $$p += length($1);
        return $1 + 0;
    }
    die "JSON parse error at pos $$p: " . substr($$t, $$p, 30) . "\n";
}

sub _decode_object {
    my ($t, $p) = @_;
    my %h;
    $$p++; # {
    _skip_ws($t, $p);
    if (substr($$t, $$p, 1) eq '}') { $$p++; return \%h; }
    while (1) {
        _skip_ws($t, $p);
        my $key = _decode_string($t, $p);
        _skip_ws($t, $p);
        $$p++; # :
        my $val = _decode_value($t, $p);
        $h{$key} = $val;
        _skip_ws($t, $p);
        my $c = substr($$t, $$p, 1);
        if ($c eq ',') { $$p++; next; }
        if ($c eq '}') { $$p++; last; }
        die "JSON parse error in object at pos $$p\n";
    }
    return \%h;
}

sub _decode_array {
    my ($t, $p) = @_;
    my @a;
    $$p++; # [
    _skip_ws($t, $p);
    if (substr($$t, $$p, 1) eq ']') { $$p++; return \@a; }
    while (1) {
        my $val = _decode_value($t, $p);
        push @a, $val;
        _skip_ws($t, $p);
        my $c = substr($$t, $$p, 1);
        if ($c eq ',') { $$p++; next; }
        if ($c eq ']') { $$p++; last; }
        die "JSON parse error in array at pos $$p\n";
    }
    return \@a;
}

sub _decode_string {
    my ($t, $p) = @_;
    $$p++; # opening "
    my $out = '';
    while (1) {
        my $c = substr($$t, $$p, 1);
        die "unterminated string\n" if $c eq '';
        if ($c eq '"') { $$p++; last; }
        if ($c eq '\\') {
            $$p++;
            my $e = substr($$t, $$p, 1);
            if ($e eq 'n') { $out .= "\n"; }
            elsif ($e eq 't') { $out .= "\t"; }
            elsif ($e eq 'r') { $out .= "\r"; }
            elsif ($e eq 'b') { $out .= "\b"; }
            elsif ($e eq 'f') { $out .= "\f"; }
            elsif ($e eq 'u') {
                my $hex = substr($$t, $$p + 1, 4);
                $out .= chr(hex($hex));
                $$p += 4;
            } else { $out .= $e; }
            $$p++;
        } else {
            $out .= $c;
            $$p++;
        }
    }
    return $out;
}

package main;

# ------------------------------------------------------------------
# curl 呼び出し
# ------------------------------------------------------------------
# プロバイダごとのHTTPヘッダ。APIキーはここで組み立て、call_api には
# ヘッダ文字列の配列として渡す(call_api自体はどっちのAIか知らない)。
sub build_headers {
    if ($PROVIDER eq 'gemini') {
        return [ "x-goog-api-key: $API_KEY", "content-type: application/json" ];
    }
    return [
        "x-api-key: $API_KEY",
        "anthropic-version: $ANTHROPIC_VERSION",
        "content-type: application/json",
    ];
}

sub call_api {
    my ($url, $headers, $body_json) = @_;

    my $tmp_req    = "/tmp/claude-agent-req-$$.json";
    my $tmp_resp   = "/tmp/claude-agent-resp-$$.json";
    my $tmp_config = "/tmp/claude-agent-curlcfg-$$.txt";

    open(my $fh, '>:encoding(UTF-8)', $tmp_req) or die "cannot write $tmp_req: $!\n";
    print $fh $body_json;
    close $fh;

    # APIキーを ps 出力に晒さないよう、コマンドライン引数ではなく
    # curlの設定ファイル(-K)経由でヘッダを渡す
    open(my $cf, '>', $tmp_config) or die "cannot write $tmp_config: $!\n";
    chmod 0600, $tmp_config;
    print $cf qq(url = "$url"\n);
    print $cf qq(request = "POST"\n);
    print $cf qq(cacert = "$CACERT"\n) if $CACERT;
    for my $h (@$headers) {
        print $cf qq(header = "$h"\n);
    }
    print $cf qq(data-binary = "\@$tmp_req"\n);
    print $cf qq(output = "$tmp_resp"\n);
    print $cf qq(write-out = "%{http_code}"\n);
    # 回線がつまっても永遠に待たないよう上限を設ける。超えたら curl が
    # エラー終了し、下で HTTP 000 として扱われる(固まらない)。
    print $cf qq(connect-timeout = 20\n);
    print $cf qq(max-time = 180\n);
    print $cf qq(silent\n);
    print $cf qq(show-error\n);
    close $cf;

    dbg("REQ $PROVIDER $MODEL -> $url  (" . length($body_json) . " bytes)");

    # 応答待ちのあいだ画面が固まって見えないよう一言出す。
    # カーソル制御のエスケープは一切使わない(古い Terminal.app が
    # 文字描画で落ちるため。消さずに1行残すだけにする)。
    emit_status("問い合わせ中");
    my $http_code = `@{[quote($CURL)]} -K @{[quote($tmp_config)]}`;
    $http_code = '' unless defined $http_code;
    $http_code =~ s/\s+//g;
    emit_status("") if $GUI;
    unlink $tmp_req, $tmp_config;

    # レスポンスは生バイトで読んでからまとめてデコードする。
    # :encoding(UTF-8) 層でそのまま読むと、マルチバイト文字がバッファ境界で
    # 割れたときに "utf8 does not map to Unicode" で落ちることがある
    # (ppc_claude_cli で踏んだのと同じ罠。日本語を多く含む長い応答で出やすい)。
    my $resp_body = '';
    if (open(my $rf, '<:raw', $tmp_resp)) {
        local $/;
        my $bytes = <$rf>;
        close $rf;
        $resp_body = defined($bytes) ? decode('UTF-8', $bytes, FB_DEFAULT) : '';
    }
    unlink $tmp_resp;

    dbg("RESP HTTP=$http_code  (" . length($resp_body) . " chars)");
    dbg("BODY:\n$resp_body");

    if ($http_code !~ /^2/) {
        if ($http_code eq '' || $http_code eq '000') {
            die "サーバーに接続できませんでした。通信環境を確認して、もう一度どうぞ。\n";
        }
        # 本文が長いと画面が流れてしまうので、頭だけ見せる。
        my $brief = $resp_body;
        $brief =~ s/\s+/ /g;
        $brief = substr($brief, 0, 300) . ' …' if length($brief) > 300;
        die "APIエラー (HTTP $http_code): $brief\n";
    }

    my $data = eval { MiniJSON::decode($resp_body) };
    if ($@ || !defined $data) {
        die "応答をうまく解釈できませんでした。もう一度どうぞ。\n";
    }
    return $data;
}

sub quote {
    my ($s) = @_;
    $s =~ s/'/'\\''/g;
    return "'$s'";
}

# ------------------------------------------------------------------
# プロバイダごとのリクエスト構築・レスポンス解析
#
# 会話履歴(@messages)は常に Anthropic の content blocks 形式
# (role => user/assistant, content => 文字列 or [{type=>text/tool_use/
# tool_result, ...}]) を内部形式として持つ。Gemini 利用時は API を呼ぶ
# 直前だけ contents/parts 形式に変換し、応答が来たらすぐ内部形式へ戻す。
# こうすることで会話ループや run_tool はプロバイダを一切気にしなくてよい。
# ------------------------------------------------------------------
sub build_request {
    my ($messages, $tools, $system) = @_;
    return $PROVIDER eq 'gemini'
        ? build_request_gemini($messages, $tools, $system)
        : build_request_anthropic($messages, $tools, $system);
}

sub build_request_anthropic {
    my ($messages, $tools, $system) = @_;
    return {
        model      => $MODEL,
        max_tokens => $MAX_TOKENS,
        system     => $system,
        messages   => $messages,
        tools      => $tools,
    };
}

sub build_request_gemini {
    my ($messages, $tools, $system) = @_;

    my @contents;
    for my $msg (@$messages) {
        my $role = $msg->{role} eq 'assistant' ? 'model' : 'user';
        my @parts;
        if (!ref $msg->{content}) {
            push @parts, { text => $msg->{content} };
        }
        else {
            for my $block (@{ $msg->{content} }) {
                if ($block->{type} eq 'text') {
                    my $part = { text => $block->{text} };
                    $part->{thoughtSignature} = $block->{thought_signature} if defined $block->{thought_signature};
                    push @parts, $part;
                }
                elsif ($block->{type} eq 'tool_use') {
                    my $part = { functionCall => { name => $block->{name}, args => $block->{input} } };
                    # Gemini 3系は functionCall を送り返す時、受け取った時と同じ
                    # thoughtSignature を付け直さないと400になる。
                    $part->{thoughtSignature} = $block->{thought_signature} if defined $block->{thought_signature};
                    push @parts, $part;
                }
                elsif ($block->{type} eq 'tool_result') {
                    # Gemini は tool_use_id ではなく名前で結果を紐付ける
                    push @parts, {
                        functionResponse => {
                            name     => $block->{name},
                            response => { output => $block->{content} },
                        },
                    };
                }
            }
        }
        push @contents, { role => $role, parts => \@parts };
    }

    my @function_declarations = map {
        +{ name => $_->{name}, description => $_->{description}, parameters => $_->{input_schema} }
    } @$tools;

    return {
        contents          => \@contents,
        systemInstruction => { parts => [ { text => $system } ] },
        tools             => [ { functionDeclarations => \@function_declarations } ],
        generationConfig  => {
            maxOutputTokens => $MAX_TOKENS,
            thinkingConfig  => _gemini_thinking_config(),
        },
    };
}

# Gemini 3系は thinkingLevel 省略時の既定が "HIGH" で、単純な質問でも最初の
# 1文字まで数十秒かかることがある。非力なマシンでの対話用途では速さ優先で
# LOW を既定にし、CLAUDE_GEMINI_THINKING=high で元に戻せるようにする。
# Gemini 2.5系は thinkingBudget(0〜24576、-1で動的)なのでモデル名で分岐。
sub _gemini_thinking_config {
    my $want_high = lc($ENV{CLAUDE_GEMINI_THINKING} || 'low') eq 'high';
    if ($MODEL =~ /^gemini-3/) {
        return { thinkingLevel => $want_high ? 'HIGH' : 'LOW' };
    }
    return { thinkingBudget => $want_high ? -1 : 0 };
}

sub parse_response {
    my ($resp) = @_;
    return $PROVIDER eq 'gemini'
        ? parse_response_gemini($resp)
        : parse_response_anthropic($resp);
}

sub parse_response_anthropic {
    my ($resp) = @_;
    if ($resp->{type} && $resp->{type} eq 'error') {
        die "APIエラー: " . MiniJSON::encode($resp) . "\n";
    }
    return @{ $resp->{content} || [] };
}

my $gemini_call_seq = 0;

sub parse_response_gemini {
    my ($resp) = @_;
    if ($resp->{error}) {
        die "APIエラー: " . MiniJSON::encode($resp->{error}) . "\n";
    }
    my $candidate = $resp->{candidates} && $resp->{candidates}[0];
    my @blocks;
    for my $part (@{ ($candidate && $candidate->{content}{parts}) || [] }) {
        if (defined $part->{text}) {
            my $block = { type => 'text', text => $part->{text} };
            $block->{thought_signature} = $part->{thoughtSignature} if defined $part->{thoughtSignature};
            push @blocks, $block;
        }
        elsif ($part->{functionCall}) {
            $gemini_call_seq++;
            my $block = {
                type  => 'tool_use',
                id    => "gemini-call-$gemini_call_seq",   # Gemini の functionCall には id が無いので代用
                name  => $part->{functionCall}{name},
                input => $part->{functionCall}{args} || {},
            };
            $block->{thought_signature} = $part->{thoughtSignature} if defined $part->{thoughtSignature};
            push @blocks, $block;
        }
    }
    return @blocks;
}

# ------------------------------------------------------------------
# 会話履歴の暗号化保存
#
# High Sierra 標準の Perl には暗号機能がなく、CPAN依存も入れたくないので
# openssl コマンドにシェルアウトしてAES-256-CBCで暗号化する。パスフレーズは
# 環境変数 CLAUDE_HIST_PASS 経由で渡し、ps出力やargv、ディスクには出さない。
# High Sierra の LibreSSL は -pbkdf2 非対応のため鍵導出はやや弱め(MD5ベース)
# だが、平文でそのまま置くよりははるかにマシ、という位置づけ。-md md5 を
# 明示して、新しめのOpenSSLとの間でも同じ鍵導出になるようにしている。
# ------------------------------------------------------------------
sub _timestamp {
    my @t = localtime();
    return sprintf('%04d%02d%02d-%02d%02d%02d',
        $t[5] + 1900, $t[4] + 1, $t[3], $t[2], $t[1], $t[0]);
}

# 一時ファイルを 0600 で作って書き込む(平文がディスクに出るのはここだけ、
# 直後に必ず unlink する)
sub _write_private {
    my ($path, $data) = @_;
    open(my $fh, '>:encoding(UTF-8)', $path) or die "一時ファイルを作成できません: $!\n";
    chmod 0600, $path;
    print $fh $data;
    close $fh;
}

# openssl のstderr(新しめのOpenSSLが出す "deprecated key derivation" 警告や
# パスフレーズ違いの "bad decrypt" など。いずれもこちらで戻り値を見て処理する)
# を飲み込んで実行する
sub _run_quiet {
    my @cmd = @_;
    open(my $olderr, '>&', \*STDERR) or return system(@cmd);
    open(STDERR, '>', '/dev/null') or do { return system(@cmd) };
    my $rc = system(@cmd);
    open(STDERR, '>&', $olderr);
    return $rc;
}

sub hist_encrypt {
    my ($plaintext, $out_path) = @_;
    my $tmp = "/tmp/claude-hist-$$-" . int(rand(1_000_000_000));
    _write_private($tmp, $plaintext);
    my $rc = _run_quiet($OPENSSL, 'enc', '-aes-256-cbc', '-md', 'md5', '-salt',
                    '-pass', 'env:CLAUDE_HIST_PASS',
                    '-in', $tmp, '-out', $out_path);
    unlink $tmp;
    return $rc == 0;
}

sub hist_decrypt {
    my ($in_path) = @_;
    my $tmp = "/tmp/claude-hist-$$-" . int(rand(1_000_000_000));
    my $rc = _run_quiet($OPENSSL, 'enc', '-d', '-aes-256-cbc', '-md', 'md5',
                    '-pass', 'env:CLAUDE_HIST_PASS',
                    '-in', $in_path, '-out', $tmp);
    if ($rc != 0) { unlink $tmp; return undef; }
    open(my $fh, '<:encoding(UTF-8)', $tmp) or do { unlink $tmp; return undef; };
    local $/;
    my $data = <$fh>;
    close $fh;
    unlink $tmp;
    return $data;
}

# パスフレーズを画面に表示せずに1行読む
{
    my $secret_hint_shown = 0;
    sub read_secret {
        my ($prompt) = @_;

        # GUI モード: パスフレーズ要求イベントを送り、返答を待つ。
        if ($GUI) {
            (my $label = $prompt) =~ s/[:：]\s*$//;
            $label =~ s/^\s+//;
            gui_send({ t => 'need_passphrase', prompt => $label });
            while (1) {
                my $r = gui_read();
                return undef unless defined $r;
                next unless $r->{t} && $r->{t} eq 'passphrase';
                return defined $r->{value} ? $r->{value} : '';
            }
        }

        # 「入力しても何も出ない」を知らないと固まったように見えるので、
        # このセッションで最初のパスフレーズ入力のときだけ一言添える。
        unless ($secret_hint_shown) {
            print "（入力中の文字は画面に表示されません。そのまま打って Enter）\n";
            $secret_hint_shown = 1;
        }
        print $prompt;
        system('stty', '-echo');
        my $line = <STDIN>;
        system('stty', 'echo');
        print "\n";
        return undef unless defined $line;
        chomp $line;
        return decode('UTF-8', $line, FB_DEFAULT);
    }
}

# 秘密(パスフレーズ or 合言葉の答え)を指定して包む/開ける。
# CLAUDE_HIST_PASS を一時的に差し替えて hist_encrypt/hist_decrypt を呼ぶ。
sub _wrap_with {
    my ($secret, $plaintext, $out_path) = @_;
    local $ENV{CLAUDE_HIST_PASS} = $secret;
    return hist_encrypt($plaintext, $out_path);
}
sub _unwrap_with {
    my ($secret, $in_path) = @_;
    local $ENV{CLAUDE_HIST_PASS} = $secret;
    return hist_decrypt($in_path);
}

# ランダムなマスター鍵(64桁hex)を生成する
sub _gen_master {
    my $hex = `@{[quote($OPENSSL)]} rand -hex 32 2>/dev/null`;
    $hex = '' unless defined $hex;
    $hex =~ s/\s+//g;
    return ($hex =~ /^[0-9a-f]{64}$/) ? $hex : undef;
}

# 包まれたマスター鍵を秘密で開ける。取り出せたらhex文字列、ダメならundef。
sub _open_master {
    my ($secret, $wrap_path) = @_;
    my $got = _unwrap_with($secret, $wrap_path);
    return undef unless defined $got;
    return $1 if $got =~ /^MASTER:([0-9a-f]{64})/;
    return undef;
}

# マスター鍵を秘密で包んで保存する
sub _save_master {
    my ($secret, $master, $wrap_path) = @_;
    my $ok = _wrap_with($secret, "MASTER:$master\n", $wrap_path);
    chmod 0600, $wrap_path if $ok;
    return $ok;
}

# 合言葉の答えを正規化する(大文字小文字と前後・連続空白を無視。
# 「Toyota Corolla」と「 toyota  corolla 」を同じ扱いにする)
sub _norm_answer {
    my ($a) = @_;
    $a = lc $a;
    $a =~ s/^\s+//;
    $a =~ s/\s+$//;
    $a =~ s/\s+/ /g;
    return $a;
}

# 合言葉(復旧用の秘密の質問)を設定/再設定する。$master は既に手元にある前提。
sub set_recovery {
    my ($master) = @_;
    print "質問を入力してください (例: 初めて買った車の名前は?): ";
    my $q = <STDIN>;
    $q = defined($q) ? decode('UTF-8', $q, FB_DEFAULT) : '';
    chomp $q;
    if ($q eq '') { print "質問が空です。合言葉は設定しませんでした。\n"; return 0; }
    my $a1 = read_secret("答え: ");
    my $a2 = read_secret("もう一度入力: ");
    unless (defined $a1 && $a1 ne '' && defined $a2 && $a1 eq $a2) {
        print "一致しませんでした。合言葉は設定しませんでした。\n";
        return 0;
    }
    unless (_save_master(_norm_answer($a1), $master, $KEY_RECOVERY)) {
        print "合言葉の保存に失敗しました。\n";
        return 0;
    }
    _write_private($KEY_RECOVERY_Q, "$q\n");
    print "合言葉を設定しました(答えは大文字小文字と前後の空白を区別しません)。\n";
    return 1;
}

# 新しいパスフレーズを2回入力させてマスター鍵を包み直す
sub reset_passphrase {
    my ($master) = @_;
    my $p1 = read_secret("新しいパスフレーズ: ");
    my $p2 = read_secret("もう一度入力: ");
    unless (defined $p1 && $p1 ne '' && defined $p2 && $p1 eq $p2) {
        print "一致しませんでした。パスフレーズは変更しません。\n";
        return 0;
    }
    if (_save_master($p1, $master, $KEY_FILE)) { print "変更しました。\n"; return 1; }
    print "変更に失敗しました。\n";
    return 0;
}

# 合言葉で復旧する。成功したらマスター鍵hexを返す(ついでにパスフレーズの
# 再設定を促す)。中止/失敗の抜け道は「空Enter」。
sub recover_with_phrase {
    my $q = '';
    if (open(my $qf, '<:encoding(UTF-8)', $KEY_RECOVERY_Q)) {
        $q = <$qf>;
        close $qf;
        chomp $q if defined $q;
    }
    print "合言葉の質問: $q\n" if defined $q && $q ne '';
    while (1) {
        my $ans = read_secret("答え (空Enterで中止): ");
        return undef unless defined $ans && $ans ne '';
        my $master = _open_master(_norm_answer($ans), $KEY_RECOVERY);
        if (defined $master) {
            print "復旧しました。\n";
            print "新しいパスフレーズを設定しますか? [y/N] ";
            my $yn = <STDIN>;
            reset_passphrase($master) if defined $yn && $yn =~ /^y/i;
            return $master;
        }
        print "答えが違います。もう一度どうぞ。\n";
    }
}

# 旧形式(.check 直接暗号化 + 履歴ファイルもパスフレーズ直接暗号化)から
# マスター鍵方式へ移行する。成功したらマスター鍵hexを返す。
sub migrate_check_file {
    print "履歴の保存形式を更新します。現在のパスフレーズを入力してください。\n";
    while (1) {
        my $pass = read_secret("履歴パスフレーズ (空Enterで中止): ");
        return undef unless defined $pass && $pass ne '';
        my $got = _unwrap_with($pass, $HISTORY_CHECK);
        if (defined $got) {
            chomp $got;
            if ($got eq 'high_sierra_claude') {
                my $master = _gen_master();
                return undef unless defined $master;
                # 既存の履歴ファイルを パスフレーズ→マスター鍵 で再暗号化
                for my $f (history_files()) {
                    my $plain = _unwrap_with($pass, "$HISTORY_DIR/$f");
                    _wrap_with($master, $plain, "$HISTORY_DIR/$f") if defined $plain;
                }
                unless (_save_master($pass, $master, $KEY_FILE)) {
                    print "更新に失敗しました。今回は履歴を保存せずに続けます。\n";
                    return undef;
                }
                unlink $HISTORY_CHECK;
                print "更新しました。\n";
                return $master;
            }
        }
        print "パスフレーズが違います。もう一度どうぞ。\n";
    }
}

# 履歴のロックを解除し、$ENV{CLAUDE_HIST_PASS} にマスター鍵をセットして
# 1 を返す。初回は新規設定、以降はパスフレーズ(または合言葉)で解錠する。
# 中止/失敗なら 0(履歴なしで続行)。
sub unlock_history {
    for my $d ("$ENV{HOME}/.claude-agent", $HISTORY_DIR) {
        mkdir($d, 0700) unless -d $d;
    }

    # GUI モード: パスフレーズ要求は必ず「1回の need_passphrase = 1回の
    # ダイアログ」にする。端末用の2回入力・合言葉・旧形式移行はここでは扱わず、
    # 素直な「新規設定 or 解錠」だけにする(GUI側が二重入力の確認をする)。
    if ($GUI) {
        return 0 if -f $HISTORY_CHECK && ! -f $KEY_FILE;   # 旧形式は端末側で移行してもらう

        if (-f $KEY_FILE) {                                 # 解錠
            while (1) {
                my $pass = read_secret("履歴パスフレーズ");
                return 0 unless defined $pass && $pass ne '';   # 空=履歴なしで起動
                my $master = _open_master($pass, $KEY_FILE);
                if (defined $master) { $ENV{CLAUDE_HIST_PASS} = $master; return 1; }
                emit_error("パスフレーズが違います。もう一度どうぞ。");
            }
        }

        # 初回設定
        my $p = read_secret("新しい履歴パスフレーズを決めてください");
        return 0 unless defined $p && $p ne '';
        my $master = _gen_master();
        return 0 unless defined $master;
        return 0 unless _save_master($p, $master, $KEY_FILE);
        $ENV{CLAUDE_HIST_PASS} = $master;
        return 1;
    }

    # 旧形式の移行
    if (-f $HISTORY_CHECK && ! -f $KEY_FILE) {
        my $master = migrate_check_file();
        if (defined $master) { $ENV{CLAUDE_HIST_PASS} = $master; return 1; }
        return 0;
    }

    # 2回目以降: パスフレーズ or 合言葉で解錠
    if (-f $KEY_FILE) {
        my $has_recovery = (-f $KEY_RECOVERY && -f $KEY_RECOVERY_Q) ? 1 : 0;
        # 回数制限なし。履歴なしで進めたいときは空Enterで抜ける。
        while (1) {
            my $prompt = $has_recovery
                ? "履歴パスフレーズ (空Enter=履歴なしで起動 / r=合言葉で復旧): "
                : "履歴パスフレーズ (空Enterで履歴なしのまま起動): ";
            my $pass = read_secret($prompt);
            unless (defined $pass && $pass ne '') {
                print "今回は履歴を保存せずに起動します。\n";
                return 0;
            }
            if ($has_recovery && $pass eq 'r') {
                my $master = recover_with_phrase();
                if (defined $master) { $ENV{CLAUDE_HIST_PASS} = $master; return 1; }
                next;
            }
            my $master = _open_master($pass, $KEY_FILE);
            if (defined $master) { $ENV{CLAUDE_HIST_PASS} = $master; return 1; }
            print "パスフレーズが違います。もう一度どうぞ。";
            print $has_recovery ? " (合言葉で復旧するには r)\n" : "\n";
        }
    }

    # 初回設定
    print "会話履歴を暗号化して $HISTORY_DIR に保存します。\n";
    print "パスフレーズを決めてください(忘れると履歴は復号できなくなります)。\n";
    my $p1 = read_secret("新しいパスフレーズ: ");
    my $p2 = read_secret("もう一度入力: ");
    unless (defined $p1 && $p1 ne '' && defined $p2 && $p1 eq $p2) {
        print "一致しませんでした。今回は履歴を保存せずに続けます。\n";
        return 0;
    }
    my $master = _gen_master();
    unless (defined $master) {
        print "鍵の生成に失敗しました(openssl rand)。今回は履歴を保存せずに続けます。\n";
        return 0;
    }
    unless (_save_master($p1, $master, $KEY_FILE)) {
        print "鍵の保存に失敗しました。今回は履歴を保存せずに続けます。\n";
        return 0;
    }
    print "設定しました。\n";

    print "\n合言葉(秘密の質問)も設定できます。パスフレーズを忘れたときの復旧用です。任意。\n";
    print "設定しますか? [y/N] ";
    my $yn = <STDIN>;
    set_recovery($master) if defined $yn && $yn =~ /^y/i;

    $ENV{CLAUDE_HIST_PASS} = $master;
    return 1;
}

# 現在の会話を暗号化して $SESSION_FILE に保存する
sub save_history {
    my ($messages_ref) = @_;
    return unless $SESSION_FILE;
    my $json = MiniJSON::encode({
        model    => $MODEL,
        started  => $STARTED,
        messages => $messages_ref,
    });
    hist_encrypt($json, $SESSION_FILE);
    chmod 0600, $SESSION_FILE;
}

# 保存済みの会話ファイル(新しい順。ファイル名先頭がタイムスタンプ)
sub history_files {
    opendir(my $dh, $HISTORY_DIR) or return ();
    my @f = grep { /\.json\.enc$/ } readdir($dh);
    closedir $dh;
    return sort { $b cmp $a } @f;
}

# 会話データから最初のユーザー発言を1行取り出す(一覧表示用)
sub first_user_line {
    my ($data) = @_;
    for my $m (@{ $data->{messages} || [] }) {
        next unless $m->{role} && $m->{role} eq 'user';
        my $c = $m->{content};
        next if ref $c;   # tool_result などの構造化contentはスキップ
        $c =~ s/\s+/ /g;
        return length($c) > 60 ? substr($c, 0, 60) . '…' : $c;
    }
    return '(発言なし)';
}

# ------------------------------------------------------------------
# ツール定義とツール実行
# ------------------------------------------------------------------
my @TOOLS = (
    {
        name => 'read_file',
        description => 'ファイルの内容を読み取る',
        input_schema => {
            type => 'object',
            properties => { path => { type => 'string', description => '読み取るファイルのパス' } },
            required => ['path'],
        },
    },
    {
        name => 'write_file',
        description => 'ファイルに内容を書き込む(上書き)',
        input_schema => {
            type => 'object',
            properties => {
                path    => { type => 'string', description => '書き込み先のパス' },
                content => { type => 'string', description => '書き込む内容' },
            },
            required => ['path', 'content'],
        },
    },
    {
        name => 'list_dir',
        description => 'ディレクトリの内容を一覧表示する',
        input_schema => {
            type => 'object',
            properties => { path => { type => 'string', description => '一覧表示するディレクトリ(省略時はカレント)' } },
            required => [],
        },
    },
    {
        name => 'run_shell',
        description => 'シェルコマンドを実行し、標準出力/標準エラーを返す',
        input_schema => {
            type => 'object',
            properties => { command => { type => 'string', description => '実行するシェルコマンド' } },
            required => ['command'],
        },
    },
);

sub confirm {
    my ($msg) = @_;

    # GUI モード: 確認イベントを送って、返ってくる reply を待つ。
    if ($GUI) {
        gui_send({ t => 'confirm', prompt => $msg });
        while (1) {
            my $r = gui_read();
            return 0 unless defined $r;                  # GUIが閉じた
            next unless $r->{t} && $r->{t} eq 'reply';
            return ($r->{value} && $r->{value} =~ /^(y|yes|1|true)$/i) ? 1 : 0;
        }
    }

    print "\n";
    print "──────── 確認 ────────\n";
    print "AIが次のことをしようとしています:\n";
    print "  $msg\n";
    print "許可するなら y、やめるなら n を入力してEnterしてください。\n";
    print "(ここはAIへの指示を書く欄ではありません。指示は y か n のあとで)\n";
    print "─────────────────────\n";
    # y/n 以外(指示文を打ってしまった等)ではキャンセルせず、聞き直す。
    # 誤って打ち込んだ一言で書き込みが飛んでしまうのを防ぐ。
    while (1) {
        print "y / n : ";
        my $ans = read_line_interactive('', 0);
        return 0 unless defined $ans;                       # Ctrl-D
        my $a = $ans;
        $a =~ s/^\s+//; $a =~ s/\s+$//;
        return 1 if $a =~ /^(y|yes|はい)$/i;
        return 0 if $a =~ /^(n|no|いいえ)$/i;
        return 0 if $a eq '';                               # Ctrl-C / 空Enter → 中止
        print "  → 「y」か「n」だけを入力してください(今の入力は実行しません)。\n";
    }
}

# ------------------------------------------------------------------
# 行編集(矢印キー対応の簡易readline)
#
# 標準の <STDIN> はカーソル移動機能を持たないため、矢印キーを押すと
# ターミナルが送る生のエスケープシーケンス(ESC [ C など)がそのまま
# 文字として画面に出てしまう。これを避けるため、stty で端末をraw
# モードにし、1バイトずつ読みながら簡易的な行編集(←→移動、
# Backspace、↑↓での履歴呼び出し)を自前で実装する。
# 外部CPANモジュール(Term::ReadLineなど)には依存しない。
# ------------------------------------------------------------------
{
    my @HISTORY;

    # デバッグ用: $ENV{CLAUDE_DEBUG_INPUT}にファイルパスを設定すると、
    # read_line_interactiveが実際に受け取った生バイトを1行ずつ追記する。
    # 実機でIME入力時に何が届いているか調べるための一時的な仕組み。
    sub _debug_log {
        return unless $ENV{CLAUDE_DEBUG_INPUT};
        open(my $fh, '>>', $ENV{CLAUDE_DEBUG_INPUT}) or return;
        print $fh @_;
        close $fh;
    }

    # UTF-8の先頭バイトからその文字が何バイトかを返す
    sub _utf8_char_len {
        my ($byte) = @_;
        my $b = ord($byte);
        return 1 if $b < 0x80;
        return 2 if ($b & 0xE0) == 0xC0;
        return 3 if ($b & 0xF0) == 0xE0;
        return 4 if ($b & 0xF8) == 0xF0;
        return 1;  # 不正なバイト列は1バイトずつ進める
    }

    # デコード済みのPerl文字列を受け取り、ターミナル上での表示幅
    # (半角=1/全角=2)を返す
    sub _display_width_chars {
        my ($text) = @_;
        my $w = 0;
        for my $ch (split //, $text) {
            my $cp = ord($ch);
            $w += (
                ($cp >= 0x1100 && $cp <= 0x115F) ||
                ($cp >= 0x2E80 && $cp <= 0xA4CF) ||
                ($cp >= 0xAC00 && $cp <= 0xD7A3) ||
                ($cp >= 0xF900 && $cp <= 0xFAFF) ||
                ($cp >= 0xFF00 && $cp <= 0xFF60) ||
                ($cp >= 0xFFE0 && $cp <= 0xFFE6)
            ) ? 2 : 1;
        }
        return $w;
    }

    # 与えられたUTF-8バイト列の、ターミナル上での表示幅を返す
    sub _display_width {
        my ($bytes) = @_;
        return 0 if $bytes eq '';
        return _display_width_chars(decode('UTF-8', $bytes, FB_DEFAULT));
    }

    # ターミナルの桁数を返す(取得できなければ80にフォールバック)
    sub _term_width {
        my $wh = `stty size 2>/dev/null`;
        return $1 if $wh =~ /^\s*\d+\s+(\d+)\s*$/;
        return 80;
    }

    # 表示幅$w(セル数)ぶん文字を描画した直後にカーソルが位置する
    # (0始まりの行, 0始まりの列)を返す。ターミナルの折り返しは、行末に
    # 達しても次の文字が来るまで改行しない"遅延ラップ"仕様のため、
    # ちょうど桁数の倍数で折り返る場合はその行の最終列に留まる。
    sub _pos_rc {
        my ($w, $cols) = @_;
        return (0, 0) if $w <= 0 || $cols <= 0;
        my $row = int(($w - 1) / $cols);
        my $col = $w % $cols;
        $col = $cols - 1 if $col == 0;  # 遅延ラップ: ちょうど桁数の倍数のときは行末に留まる
        return ($row, $col);
    }

    # プロンプトを表示しつつ1行読み込む。
    #
    # 既定は「素の入力」: 端末を raw にせず <STDIN> で1行読むだけ。
    # 理由 — 矢印キー対応の自作行編集は、キー入力のたびに端末へ大量の
    # カーソル移動・全行再描画のエスケープシーケンスを送る。High Sierra の
    # Terminal.app 2.8.3 はこの負荷(特に日本語=CoreText グリフ描画)で
    # グリフ描画中に heap corruption を起こして abort することがある
    # (Terminal 側のバグ。crash report で確認済み)。実用上、行編集より
    # 「落ちないこと」を優先する。
    #
    # CLAUDE_FANCY_INPUT=1 で従来の行編集(←→移動・↑↓履歴)に戻せる。
    sub read_line_interactive {
        my ($prompt, $use_history) = @_;
        $use_history = 1 unless defined $use_history;

        unless ($ENV{CLAUDE_FANCY_INPUT}) {
            (my $p = $prompt) =~ s/^\n+//;
            print "\n" if $prompt =~ /^\n/;
            print $p;
            my $line = <STDIN>;
            return undef unless defined $line;   # EOF

            # 複数行を貼り付けると1行=1メッセージに割れてしまうのを防ぐ。
            # 最初の行を読んだ直後、まだ入力がバッファに残っていれば(=貼り付け)、
            # 続く行も同じメッセージとしてまとめる。人が1行ずつ考えて打つ場合は
            # 次の行まで間があくので、この待ち時間(50ms)には引っかからない。
            eval {
                my $rin = '';
                vec($rin, fileno(STDIN), 1) = 1;
                while (select(my $r = $rin, undef, undef, 0.05)) {
                    my $more = <STDIN>;
                    last unless defined $more;
                    $line .= $more;
                }
            };

            $line =~ s/\r?\n\z//;                 # 末尾の改行だけ落とす(中の改行は残す)
            return $line;                         # 生バイト(呼び出し側でデコード)
        }

        my $orig_stty = `stty -g`;
        chomp $orig_stty;
        my $term_cols = _term_width();
        # -opostが無いと、環境によっては出力後処理(特にocrnl)が有効なままで
        # 再描画に使う"\r"が改行として扱われ、行を上書きするはずが毎回新しい
        # 行を作ってしまう(結果、入力するたびにどんどん改行されていく)。
        system('stty', 'raw', '-echo', '-opost');

        my $buf = '';                    # 生バイト列
        my $pos = 0;                     # カーソル位置(バイト単位、常に文字境界)
        my $hist_idx = scalar(@HISTORY); # 履歴カーソル(配列末尾 = 新規入力中)
        my $saved_buf = '';              # 履歴を辿る前の入力を退避しておく

        # $promptの先頭改行(例: "\nご用件をどうぞ> ")は最初の表示でだけ使う。
        # 再描画のたびにこれをそのまま含めて出すと、キー入力するたびに
        # 改行が挿入され続けて新しい行がどんどん増えてしまう。
        (my $redraw_prompt = $prompt) =~ s/^\n+//;

        # redraw_promptだけを表示した状態(bufが空)で何行分の表示になるかを初期値とする。
        my $rows_used = (_pos_rc(_display_width_chars($redraw_prompt), $term_cols))[0] + 1;

        my $redraw = sub {
            # $bufは生バイトのUTF-8。STDOUTには:encoding(UTF-8)層が付いているので
            # 一度Perl文字列にデコードしてから渡さないと二重エンコードで文字化けする。
            my $text   = decode('UTF-8', $buf, FB_DEFAULT);
            my $before = decode('UTF-8', substr($buf, 0, $pos), FB_DEFAULT);
            my $full_text   = $redraw_prompt . $text;
            my $full_width  = _display_width_chars($full_text);
            my $cursor_width = _display_width_chars($redraw_prompt . $before);

            # 前回の再描画で使った行数ぶんカーソルを先頭行まで戻し、そこから
            # 画面末尾までを丸ごとクリアする。折り返した行が複数あっても、
            # 最終行だけをクリアする"\r\x1b[K"では前の行が消えずに残って
            # しまい、入力するたびに同じ文字列が積み重なって表示される
            # バグの原因になっていた。
            print "\x1b[" . ($rows_used - 1) . "A" if $rows_used > 1;
            print "\r\x1b[0J", $full_text;

            my $end_row = (_pos_rc($full_width, $term_cols))[0];
            $rows_used = $end_row + 1;

            if ($cursor_width < $full_width) {
                my ($cur_row, $cur_col) = _pos_rc($cursor_width, $term_cols);
                print "\x1b[" . ($end_row - $cur_row) . "A" if $end_row > $cur_row;
                print "\x1b[" . ($cur_col + 1) . "G";
            }
        };

        print $prompt;
        _debug_log("=== read_line_interactive start ===\n");

        # 誤って先読みしてしまったバイトを次のループへ戻すためのプッシュバック
        # キュー。マルチバイト文字の続きだと思って読んだバイトが実際には
        # continuationバイトの形式(10xxxxxx)でなかった場合に使う。
        my @pending;
        my $read_one_byte = sub {
            return shift @pending if @pending;
            my $ch;
            my $n = sysread(STDIN, $ch, 1);
            return (defined $n && $n > 0) ? $ch : undef;
        };
        # Mac OS X の Terminal.app は、IME(日本語入力など)で確定した
        # テキストを渡す際、各バイトの前に0x16(Ctrl-V。端末で伝統的に
        #「次の1文字をそのまま扱う(LNEXT)」の合図として使われるバイト)を
        # 付けて送ってくることがある。このプログラムはraw modeで自前で
        # 入力を処理しておりLNEXTの解釈をしていないため、何もしないと
        # この合図のバイト自体がゴミとして文字列に混入し、UTF-8が壊れて
        # 文字化けする。ここで0x16を読み飛ばし、次のバイトを本来のデータ
        # として扱う。
        my $read_byte = sub {
            my $ch = $read_one_byte->();
            if (defined $ch && $ch eq "\x16") {
                $ch = $read_one_byte->();
            }
            return $ch;
        };

        my $result;
        my $ctrld_seen = 0;   # 空行での Ctrl-D。1回目は警告、2回で終了。
        RAW_LOOP: while (1) {
            my $ch = $read_byte->();
            if (!defined $ch) {
                _debug_log("EOF\n");
                dbg("readline: real EOF on STDIN");
                $result = undef;  # 本物のEOF(標準入力が閉じた)
                last RAW_LOOP;
            }
            my $b = ord($ch);
            _debug_log(sprintf("byte: %02x (%s)\n", $b, ($b >= 0x20 && $b < 0x7f) ? chr($b) : ''));

            if ($b == 13 || $b == 10) {       # Enter
                _debug_log(sprintf("-> ENTER, buf hex=%s\n", unpack('H*', $buf)));
                print "\r\n";
                $result = $buf;
                last RAW_LOOP;
            }
            elsif ($b == 3) {                  # Ctrl-C: 行をキャンセルして空行扱い
                print "\r\n";
                $result = '';
                last RAW_LOOP;
            }
            elsif ($b == 4) {                  # Ctrl-D
                # 誤爆で1発終了しないよう、空行では2回連続で押されたときだけEOF。
                if ($buf eq '') {
                    $ctrld_seen++;
                    if ($ctrld_seen >= 2) {
                        dbg("readline: Ctrl-D x2 -> EOF");
                        $result = undef;
                        last RAW_LOOP;
                    }
                    print "\r\n(終了するなら exit と入力するか、もう一度 Ctrl-D)\n";
                    print $redraw_prompt;
                    $rows_used = (_pos_rc(_display_width_chars($redraw_prompt), $term_cols))[0] + 1;
                }
            }
            elsif ($b == 127 || $b == 8) {      # Backspace
                if ($pos > 0) {
                    my $start = $pos - 1;
                    $start-- while $start > 0 && (ord(substr($buf, $start, 1)) & 0xC0) == 0x80;
                    substr($buf, $start, $pos - $start, '');
                    $pos = $start;
                    $redraw->();
                }
            }
            elsif ($b == 27) {                  # ESC: カーソルキーなど
                my $c2 = $read_byte->();
                next RAW_LOOP unless defined $c2;
                if ($c2 eq '[') {
                    my $c3 = $read_byte->();
                    next RAW_LOOP unless defined $c3;
                    if ($c3 eq 'C') {            # →
                        if ($pos < length($buf)) {
                            $pos += _utf8_char_len(substr($buf, $pos, 1));
                            $redraw->();
                        }
                    }
                    elsif ($c3 eq 'D') {         # ←
                        if ($pos > 0) {
                            my $start = $pos - 1;
                            $start-- while $start > 0 && (ord(substr($buf, $start, 1)) & 0xC0) == 0x80;
                            $pos = $start;
                            $redraw->();
                        }
                    }
                    elsif ($use_history && $c3 eq 'A') {  # ↑ 履歴を遡る
                        if ($hist_idx > 0) {
                            $saved_buf = $buf if $hist_idx == @HISTORY;
                            $hist_idx--;
                            $buf = $HISTORY[$hist_idx];
                            $pos = length($buf);
                            $redraw->();
                        }
                    }
                    elsif ($use_history && $c3 eq 'B') {  # ↓ 履歴を進める
                        if ($hist_idx < @HISTORY) {
                            $hist_idx++;
                            $buf = ($hist_idx == @HISTORY) ? $saved_buf : $HISTORY[$hist_idx];
                            $pos = length($buf);
                            $redraw->();
                        }
                    }
                    elsif ($c3 eq '3') {         # Delete キー (ESC [ 3 ~)
                        my $c4 = $read_byte->();
                        if (defined $c4 && $pos < length($buf)) {
                            substr($buf, $pos, _utf8_char_len(substr($buf, $pos, 1)), '');
                            $redraw->();
                        }
                    }
                }
            }
            else {                               # 通常の文字(UTF-8の生バイト)
                # マルチバイト文字の途中(バイトが揃っていない状態)でredrawすると
                # decode()が不完全な列を「�」に化けさせてしまうため、1文字分の
                # バイトが揃うまで読んでからバッファに追加・再描画する。
                # ただし、続くバイトが本当にUTF-8のcontinuationバイト(10xxxxxx)
                # でなければ、それは別の文字/キーの先頭バイトなので読み戻す
                # (でないと、本来の入力を誤って飲み込んでしまい、以降の入力が
                # 効かなくなってしまう)。
                my $need = _utf8_char_len($ch) - 1;
                my $char = $ch;
                while ($need > 0) {
                    my $cont = $read_byte->();
                    last unless defined $cont;
                    _debug_log(sprintf("  continuation byte: %02x\n", ord($cont)));
                    if ((ord($cont) & 0xC0) != 0x80) {
                        unshift @pending, $cont;
                        last;
                    }
                    $char .= $cont;
                    $need--;
                }
                substr($buf, $pos, 0) = $char;
                $pos += length($char);
                $redraw->();
            }
        }

        system('stty', $orig_stty) if defined $orig_stty && $orig_stty ne '';

        if ($use_history && defined $result && $result ne '') {
            push @HISTORY, $result;
        }
        return $result;
    }
}

sub run_tool {
    my ($name, $input) = @_;

    if ($name eq 'read_file') {
        my $path = $input->{path};
        open(my $fh, '<:encoding(UTF-8)', $path) or return "エラー: $path を開けません: $!";
        local $/;
        my $content = <$fh>;
        close $fh;
        return $content;
    }
    elsif ($name eq 'write_file') {
        my $path = $input->{path};
        unless (confirm("ファイル '$path' に書き込みます")) {
            return "ユーザーが書き込みをキャンセルしました";
        }
        open(my $fh, '>:encoding(UTF-8)', $path) or return "エラー: $path に書き込めません: $!";
        print $fh $input->{content};
        close $fh;
        return "書き込み完了: $path";
    }
    elsif ($name eq 'list_dir') {
        my $path = $input->{path} || '.';
        opendir(my $dh, $path) or return "エラー: $path を開けません: $!";
        my @entries = sort grep { $_ ne '.' && $_ ne '..' } readdir($dh);
        closedir $dh;
        return join("\n", @entries);
    }
    elsif ($name eq 'run_shell') {
        my $command = $input->{command};
        unless (confirm("コマンドを実行します: $command")) {
            return "ユーザーが実行をキャンセルしました";
        }
        my $output = `$command 2>&1`;
        return $output eq '' ? '(出力なし)' : $output;
    }
    else {
        return "不明なツール: $name";
    }
}

# ------------------------------------------------------------------
# 会話ループ
# ------------------------------------------------------------------
my @messages;

# --- 履歴: ロック解除 / 一覧表示 / 再開 ---
if ($HISTORY_ENABLED) {
    $HISTORY_ENABLED = unlock_history();
}

if ($CHANGE_PASS) {
    unless ($HISTORY_ENABLED) { print "履歴は利用できません。\n"; exit 1; }
    reset_passphrase($ENV{CLAUDE_HIST_PASS});   # unlock後、CLAUDE_HIST_PASSにはマスター鍵が入っている
    exit 0;
}

if ($SET_RECOVERY) {
    unless ($HISTORY_ENABLED) { print "履歴は利用できません。\n"; exit 1; }
    set_recovery($ENV{CLAUDE_HIST_PASS});
    exit 0;
}

if ($LIST_HISTORY) {
    unless ($HISTORY_ENABLED) { print "履歴は利用できません。\n"; exit 1; }
    my @files = history_files();
    unless (@files) { print "保存済みの会話はありません。\n"; exit 0; }
    my $i = 1;
    for my $f (@files) {
        my $raw = hist_decrypt("$HISTORY_DIR/$f");
        my $line = '(復号できません)';
        if (defined $raw) {
            my $d = eval { MiniJSON::decode($raw) };
            $line = $d ? (($d->{started} || $f) . '  ' . first_user_line($d)) : '(壊れています)';
        }
        printf "  %2d) %s\n", $i++, $line;
    }
    exit 0;
}

if ($RESUME) {
    unless ($HISTORY_ENABLED) { print "履歴は利用できません。\n"; exit 1; }
    my @files = history_files();
    unless (@files) { print "再開できる会話はありません。\n"; exit 0; }
    my @decoded;
    my $i = 1;
    for my $f (@files) {
        my $raw = hist_decrypt("$HISTORY_DIR/$f");
        my $d = defined($raw) ? eval { MiniJSON::decode($raw) } : undef;
        push @decoded, { file => $f, data => $d };
        printf "  %2d) %s\n", $i++,
            $d ? (($d->{started} || $f) . '  ' . first_user_line($d)) : "$f (読めません)";
    }
    print "再開する番号を入力 [1]: ";
    my $sel = <STDIN>;
    $sel = defined($sel) ? $sel + 0 : 1;
    $sel = 1 if $sel < 1 || $sel > scalar(@decoded);
    my $chosen = $decoded[$sel - 1];
    if ($chosen->{data} && $chosen->{data}{messages}) {
        @messages = @{ $chosen->{data}{messages} };
        $SESSION_FILE = "$HISTORY_DIR/" . $chosen->{file};   # 同じファイルに続けて保存
        print "会話を再開します(" . scalar(@messages) . "メッセージ)。\n";
    } else {
        print "その会話は読み込めませんでした。新しい会話を始めます。\n";
    }
}

# 新規会話のときの保存先
if ($HISTORY_ENABLED && !$SESSION_FILE) {
    $SESSION_FILE = "$HISTORY_DIR/$STARTED.json.enc";
}

# --- GUI モード: JSON でやり取りするループ(Python/tkinter から駆動) ---
if ($GUI) {
    gui_send({
        t         => 'ready',
        provider  => $PROVIDER,
        model     => $MODEL,
        history   => $HISTORY_ENABLED ? 1 : 0,
        models    => [ map { { id => $_->[0], label => $_->[1] } } @MODEL_CHOICES ],
        messages  => scalar(@messages),
    });
    while (1) {
        my $req = gui_read();
        last unless defined $req;                       # GUI が閉じた = EOF
        my $type = $req->{t} || '';
        last if $type eq 'quit';
        if ($type eq 'cwd') {
            # GUI のコマンドパネルで cd した先を、AI のツールにも反映する。
            my $p = $req->{path};
            if (defined $p && $p ne '' && -d $p) { chdir($p); dbg("cwd -> $p"); }
            next;
        }
        next unless $type eq 'user';
        my $text = defined $req->{text} ? $req->{text} : '';
        next if $text eq '';

        my $r = eval { handle_turn($text) };
        if ($@) {
            dbg("turn error(gui): $@");
            emit_error("うまく処理できませんでした(続けられます)。");
            pop @messages if @messages
                && ($messages[-1]{role} eq 'assistant' || ref $messages[-1]{content});
        }
        eval { save_history(\@messages) if $HISTORY_ENABLED };
        gui_send({ t => 'turn_done' });
        last if defined $r && $r eq 'quit';
    }
    gui_send({ t => 'bye' });
    exit 0;
}

print "=== high_sierra Advisor ===\n";
print $HISTORY_ENABLED ? "履歴: 暗号化して保存します\n" : "履歴: 保存しません\n";
if (@MODEL_CHOICES) {
    show_model_menu();
} else {
    print "[$PROVIDER / $MODEL]\n";
}
print "\nこんにちは。(終了するときは exit と入力)\n";

# 1ターン分の処理。'quit' を返したら会話終了、それ以外は継続。
# ここで die しても、呼び出し側の eval が受け止めてプログラムは落ちない。
sub handle_turn {
    my ($input) = @_;
    dbg("turn start: msgs=" . scalar(@messages) . " input=" . substr($input, 0, 80));

    return 'quit' if $input eq 'exit';

    # 一覧を出す(端末のみ。GUIは起動時に一覧を受け取っている)
    if ($input eq '/model' || $input eq '/models' || $input eq '/m' || $input eq '?') {
        show_model_menu() unless $GUI;
        return;
    }

    # 番号だけ打ったら、その番号のAIに切り替える(人間に一番やさしい操作)
    if ($input =~ /^\s*(\d+)\s*$/ && @MODEL_CHOICES) {
        my $n = $1;
        if ($n >= 1 && $n <= @MODEL_CHOICES) {
            my $id = $MODEL_CHOICES[$n - 1][0];
            ($id eq $MODEL)
                ? emit_note("すでに [$PROVIDER / $MODEL] です。")
                : switch_to_model($id);
            return;
        }
        # 範囲外の数字はふつうの発言として扱う(下へ流れる)
    }

    # /model 3 や /model <ID> でも指定できる
    if ($input =~ m{^/models?\s+(\S.*?)\s*$}) {
        my $arg = $1;
        my $id = ($arg =~ /^\d+$/ && @MODEL_CHOICES && $arg >= 1 && $arg <= @MODEL_CHOICES)
            ? $MODEL_CHOICES[$arg - 1][0] : $arg;
        ($id eq $MODEL)
            ? emit_note("すでに [$PROVIDER / $MODEL] です。")
            : switch_to_model($id);
        return;
    }

    # プロバイダ(Claude/Gemini)だけ切り替える
    if ($input eq '/claude' || $input eq '/gemini') {
        my $target = $input eq '/claude' ? 'anthropic' : 'gemini';
        if ($target eq $PROVIDER) {
            emit_note("すでに [$PROVIDER / $MODEL] です。");
        }
        elsif (switch_provider($target)) {
            persist_env('CLAUDE_PROVIDER', $PROVIDER);
            persist_env('CLAUDE_MODEL', $MODEL);
            emit_note("→ [$PROVIDER / $MODEL] にしました。会話はそのまま引き継がれます。");
            gui_send({ t => 'model', provider => $PROVIDER, model => $MODEL }) if $GUI;
        }
        return;
    }

    push @messages, { role => 'user', content => $input };

    while (1) {
        dbg("build_request: msgs=" . scalar(@messages));
        my $body = build_request(\@messages, \@TOOLS, $SYSTEM_PROMPT);
        dbg("encode+call_api");
        my $resp = eval { call_api($API_URL, build_headers(), MiniJSON::encode($body)) };
        if ($@) {
            # 通信エラーなど。素のユーザー発言のターンなら取り消して戻る
            # (ツール応答の途中なら履歴を壊さないよう残す)。
            emit_error($@);
            pop @messages if @messages && !ref $messages[-1]{content};
            return;
        }

        my @content_blocks = eval { parse_response($resp) };
        if ($@) {
            emit_error($@);
            pop @messages if @messages && !ref $messages[-1]{content};
            return;
        }

        # 空の応答(安全フィルタ・トークン上限で本文なし 等)。空の assistant
        # ターンを履歴に入れると以後ずっと壊れるので、入れずに戻る。
        unless (@content_blocks) {
            emit_error("(AIからの応答が空でした。言い方を変えてもう一度どうぞ)");
            pop @messages if @messages && !ref $messages[-1]{content};
            return;
        }

        push @messages, { role => 'assistant', content => \@content_blocks };

        my @tool_results;
        for my $block (@content_blocks) {
            my $t = $block->{type} || '';
            if ($t eq 'text') {
                emit_text($block->{text});
            }
            elsif ($t eq 'tool_use') {
                emit_tool($block->{name}, $block->{input});
                my $result = eval { run_tool($block->{name}, $block->{input}) };
                $result = "ツール実行でエラーが出ました: $@" if $@;
                push @tool_results, {
                    type        => 'tool_result',
                    tool_use_id => $block->{id},
                    name        => $block->{name},   # Gemini は名前で結果を紐付ける
                    content     => $result,
                };
            }
        }

        if (@tool_results) {
            push @messages, { role => 'user', content => \@tool_results };
            next; # ツール結果を送ってもう一度APIを呼ぶ
        }
        return; # tool_useが無ければこのターンは終了
    }
}

# --- メインループ ---
# 1ターンごとに eval で囲み、どこで die が起きてもプログラム全体は落とさず
# 入力プロンプトに戻す。端末設定も毎回念のため戻す。
while (1) {
    dbg("--- waiting for input (readline) ---");
    my $input = eval { read_line_interactive("\nご用件をどうぞ> ") };
    if ($@) {
        restore_tty();
        dbg("readline error: $@");
        print "\n[入力エラー] 続けます。\n";
        next;
    }
    dbg("readline returned: " . (defined $input ? "len=" . length($input) : "undef(EOF)"));
    last unless defined $input;

    $input = eval { decode('UTF-8', $input, FB_DEFAULT) };
    $input = '' unless defined $input;
    next if $input eq '';

    my $r = eval { handle_turn($input) };
    if ($@) {
        restore_tty();
        dbg("turn error: $@");
        print "\n────────\n";
        print "うまく処理できませんでした(このまま続けられます)。\n";
        print "何度も起きるようなら、一度 exit して\n";
        print "  CLAUDE_DEBUG_LOG=\$HOME/advisor-debug.txt advisor\n";
        print "で起動し直し、~/advisor-debug.txt を見せてください。\n";
        print "────────\n";
        # 半端な履歴を1つ戻して、次の発言から再開できるようにする
        pop @messages if @messages
            && ($messages[-1]{role} eq 'assistant' || ref $messages[-1]{content});
        next;
    }
    last if defined $r && $r eq 'quit';

    eval { save_history(\@messages) if $HISTORY_ENABLED };
    dbg("save_history error: $@") if $@;
}

print "\nさようなら。\n";
