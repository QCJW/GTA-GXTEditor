import os
import subprocess
import sys
import platform

def package_to_exe():
    # 检查PyInstaller是否安装
    try:
        import PyInstaller
    except ImportError:
        print("PyInstaller未安装，正在安装...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
    
    # 检查main.py是否存在
    if not os.path.exists("main.py"):
        print("错误：当前目录下未找到main.py文件")
        return
    
    # 检查图标文件是否存在
    icon_path = "app_icon.ico"
    icon_arg = ""
    if os.path.exists(icon_path):
        icon_arg = f"--icon={icon_path}"
    else:
        print("警告：未找到app_icon.ico文件，将使用默认图标")
    
    # 处理数据文件（确保图标文件被打包）
    # 根据操作系统设置路径分隔符
    sep = ";" if platform.system() == "Windows" else ":"
    data_files = [f"{icon_path}{sep}."]  # 将图标文件打包到根目录
    
    # 构建数据文件参数
    data_args = []
    for data in data_files:
        data_args.extend(["--add-data", data])
    
    # 构建PyInstaller命令
    command = [
        "pyinstaller",
        "--onefile",
        "--windowed",
        "--name=MyApp",
        *data_args,  # 添加数据文件参数
        icon_arg,
        "main.py"
    ]
    
    # 过滤掉空的参数
    command = [arg for arg in command if arg]
    
    try:
        # 执行打包命令
        print("开始打包...")
        subprocess.check_call(command)
        print("打包完成！可执行文件位于dist目录下")
        
        # 清理临时文件
        print("清理临时文件...")
        if os.path.exists("build"):
            import shutil
            shutil.rmtree("build")
        if os.path.exists("MyApp.spec"):
            os.remove("MyApp.spec")
            
    except Exception as e:
        print(f"打包过程中出错：{str(e)}")

if __name__ == "__main__":
    package_to_exe()
    input("按回车键退出...")
