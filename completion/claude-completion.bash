# claude-completion.bash — high_sierra_claude の `claude` コマンド用bash補完
#
# High Sierra標準のbash 3.2でも動くよう、連想配列などbash4以降の機能は
# 使わずに書いてある。~/.bash_profile から source して使う
# (setup.sh が自動で設定する)。

_claude_completions() {
    local cur prev opts models_file
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    opts="-h --help --version -m --model --select-model --list-models"
    models_file="$HOME/claude-build/models.txt"

    case "$prev" in
        -m|--model)
            if [ -f "$models_file" ]; then
                local ids
                ids=$(awk -F'|' '{print $1}' "$models_file")
                COMPREPLY=( $(compgen -W "$ids" -- "$cur") )
            fi
            return 0
            ;;
    esac

    COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
    return 0
}
complete -F _claude_completions claude
