-- claude-launcher.applescript
-- 「Claude.app」の中身。ダブルクリックすると Terminal.app が開いて
-- claude コマンドが起動する。ターミナルの使い方を知らない人でも、
-- Dock やデスクトップのアイコンから開発エージェントを始められるようにするためのもの。
--
-- setup.sh が osacompile でこれを ~/Applications/Claude.app にコンパイルする。
-- (osacompile はどの macOS にも標準で入っているので追加ビルドは不要)

on run
	tell application "Terminal"
		activate
		-- 新しいウィンドウでログインシェルが起動し ~/.bash_profile が読まれるので、
		-- setup.sh が PATH に足した ~/bin の claude がそのまま見つかる。
		do script "clear; claude"
	end tell
end run
