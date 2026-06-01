# 3D打印一键自动化技能

## 概述

此技能用于自动化Bambu Lab 3D打印机的完整流程：
- 模型缩放调整
- 支撑配置优化
- 自动切片
- 发送到打印机

## 使用场景

1. **用户想要一键打印模型**
2. **需要调整模型尺寸**
3. **需要优化支撑配置**
4. **需要批量处理多个模型**

## 核心命令

### 1. 检查和读取3MF文件

```python
import zipfile
import json

def read_3mf_config(file_path):
    """读取3MF文件中的配置"""
    with zipfile.ZipFile(file_path, 'r') as z:
        config = json.loads(z.read('Metadata/project_settings.config'))
        return config

def read_3mf_model_info(file_path):
    """读取3MF模型尺寸信息"""
    with zipfile.ZipFile(file_path, 'r') as z:
        model_xml = z.read('3D/3dmodel.model').decode('utf-8')
        # 解析transform矩阵获取尺寸
        import re
        matrices = re.findall(r'transform="([^"]*)"', model_xml)
        return matrices
```

### 2. 修改支撑配置

```python
def update_support_config(config, settings):
    """
    更新支撑配置
    
    settings = {
        "branch_diameter": "12",  # 主干直径 (2-15mm)
        "threshold_angle": "45",   # 支撑角度 (30-60°)
        "wall_count": "4",         # 墙数 (0-4)
        "interface_layers": "6",   # 界面层数 (2-6)
    }
    """
    config.update({
        "enable_support": "1",
        "support_type": "tree(auto)",
        "support_threshold_angle": settings.get("threshold_angle", "45"),
        "tree_support_branch_diameter": settings.get("branch_diameter", "3"),
        "tree_support_tip_diameter": str(float(settings.get("branch_diameter", "3")) * 0.2),
        "tree_support_branch_angle": "65" if float(settings.get("branch_diameter", "3")) > 6 else "50",
        "tree_support_wall_count": settings.get("wall_count", "1"),
        "support_interface_top_layers": settings.get("interface_layers", "3"),
        "support_interface_bottom_layers": settings.get("interface_layers", "3"),
        "support_xy_distance": "1.0",
        "support_speed": "150" if float(settings.get("branch_diameter", "3")) > 6 else "80",
    })
    return config
```

### 3. 缩放3MF模型

```python
import zipfile
import re

def scale_3mf_model(input_file, output_file, scale):
    """
    缩放3MF模型
    
    矩阵格式: 3x4矩阵，元素0,4,8分别控制X,Y,Z缩放
    """
    with zipfile.ZipFile(input_file, 'r') as zip_in:
        model_data = zip_in.read('3D/3dmodel.model').decode('utf-8')
        
        def scale_transform(match):
            matrix_str = match.group(1)
            try:
                values = matrix_str.split()
                if len(values) == 12:
                    # 索引0,4,8分别是X,Y,Z缩放因子
                    values[0] = str(float(values[0]) * scale)
                    values[4] = str(float(values[4]) * scale)
                    values[8] = str(float(values[8]) * scale)
                    return f'transform="{" ".join(values)}"'
            except:
                pass
            return match.group(0)
        
        scaled_model = re.sub(r'transform="([^"]*)"', scale_transform, model_data)
        
        with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_DEFLATED) as zip_out:
            for item in zip_in.namelist():
                data = zip_in.read(item)
                if item == '3D/3dmodel.model':
                    zip_out.writestr(item, scaled_model.encode('utf-8'))
                else:
                    zip_out.writestr(item, data)
```

### 4. 检查打印机状态

```python
import paho.mqtt.client as mqtt
import json
import ssl

def get_printer_status(ip, access_code, serial):
    """通过MQTT获取打印机状态"""
    client = mqtt.Client()
    client.username_pw_set("bblp", access_code)
    client.tls_set(cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)
    
    status = {}
    def on_message(c, u, msg):
        try:
            data = json.loads(msg.payload)
            if 'print' in data:
                status.update(data['print'])
        except:
            pass
    
    client.on_connect = lambda c,u,f,rc: c.subscribe(f'device/{serial}/report')
    client.on_message = on_message
    
    client.connect(ip, 8883, 5)
    client.loop_start()
    time.sleep(2)
    client.loop_stop()
    client.disconnect()
    
    return {
        'state': status.get('gcode_state', '未知'),
        'bed_temp': status.get('bed_temper', 'N/A'),
        'nozzle_temp': status.get('nozzle_temper', 'N/A'),
        'progress': status.get('mc_percent', 'N/A'),
    }
```

### 5. 完整一键流程

```python
def one_click_print(input_file, scale=1.0, support_settings=None):
    """
    一键打印完整流程
    
    Args:
        input_file: 输入3MF文件路径
        scale: 缩放比例 (默认1.0)
        support_settings: 支撑配置字典
    
    Returns:
        output_file: 生成的文件路径
    """
    from pathlib import Path
    
    input_path = Path(input_file)
    output_file = input_path.parent / f"{input_path.stem}_optimized.3mf"
    
    # 1. 读取原配置
    with zipfile.ZipFile(input_file, 'r') as z:
        config = json.loads(z.read('Metadata/project_settings.config'))
        model_data = z.read('3D/3dmodel.model').decode('utf-8')
    
    # 2. 更新支撑配置
    if support_settings:
        config = update_support_config(config, support_settings)
    
    # 3. 缩放模型
    if scale != 1.0:
        import re
        def scale_transform(match):
            matrix_str = match.group(1)
            try:
                values = matrix_str.split()
                if len(values) == 12:
                    values[0] = str(float(values[0]) * scale)
                    values[4] = str(float(values[4]) * scale)
                    values[8] = str(float(values[8]) * scale)
                    return f'transform="{" ".join(values)}"'
            except:
                pass
            return match.group(0)
        model_data = re.sub(r'transform="([^"]*)"', scale_transform, model_data)
    
    # 4. 写入新文件
    with zipfile.ZipFile(input_file, 'r') as zip_in:
        with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_DEFLATED) as zip_out:
            for item in zip_in.namelist():
                data = zip_in.read(item)
                if item == 'Metadata/project_settings.config':
                    zip_out.writestr(item, json.dumps(config, indent=4))
                elif item == '3D/3dmodel.model':
                    zip_out.writestr(item, model_data.encode('utf-8'))
                else:
                    zip_out.writestr(item, data)
    
    return output_file
```

## 支撑粗细配置参考

| 粗细级别 | 直径 | 适用场景 |
|---------|------|---------|
| 细 | 2mm | 小模型，省料 |
| 标准 | 3-4mm | 一般模型 |
| 粗 | 6-8mm | 大模型，需要稳固支撑 |
| 超粗 | 10-12mm | 超大模型，支撑绝对不能断 |
| 巨粗 | 15mm+ | 特殊需求 |

## 常见问题

### Q: 支撑拆除困难？
A: 增加`support_xy_distance`到1.0mm，增加界面层数到5-6层

### Q: 支撑断裂？
A: 增加`tree_support_branch_diameter`到8mm以上，增加`tree_support_wall_count`到3-4层

### Q: 模型太小？
A: 使用scale参数放大，建议1.5-2.5倍

## 示例

```python
# 一键生成超大超粗版本
output = one_click_print(
    "lobster.3mf",
    scale=2.5,
    support_settings={
        "branch_diameter": "12",
        "threshold_angle": "55",
        "wall_count": "4",
        "interface_layers": "6",
    }
)
print(f"生成文件: {output}")
```
