@echo off
:: 获取提交备注
set /p commit_msg="请输入提交备注: "

:: 执行 Git 命令
git add .
git commit -m "%commit_msg%"
git push origin master
echo 提交并推送完成: %commit_msg%
pause
