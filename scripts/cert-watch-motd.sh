#!/bin/sh
# 99-cert-watch —— 只在证书有问题时往登录 banner 里塞一行（内容由 cert_watch.sh 写）
a=/var/lib/cert-watch/alert.txt
[ -r "$a" ] && cat "$a"
exit 0
