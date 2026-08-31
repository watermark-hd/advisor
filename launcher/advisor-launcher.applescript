-- advisor-launcher.applescript
-- 「Advisor.app」の中身。ダブルクリックすると Terminal.app が開いて
-- advisor コマンドが起動する。ターミナルの使い方を知らない人でも、
-- Dock やデスクトップのアイコンからAIエージェントを始められるようにするためのもの。
--
-- setup.sh が osacompile でこれを ~/Applications/Advisor.app にコンパイルする。
-- (osacompile はどの macOS にも標準で入っているので追加ビルドは不要)

on run
	tell application "Terminal"
		activate
		-- 新しいウィンドウでログインシェルが起動し ~/.bash_profile が読まれるので、
		-- setup.sh が PATH に足した ~/bin の advisor がそのまま見つかる。
		do script "clear; advisor"
	end tell
end run
