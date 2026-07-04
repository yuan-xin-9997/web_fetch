from __future__ import annotations

from webfetch_service.adapters import ChinaOfficialProfileAdapter


async def test_cppcc_profile_layout() -> None:
    html = """
    <html><head><title>何立峰简历</title></head><body>
      <div class="navigation">无关导航</div>
      <div class="con">同名但不是正文的短容器</div>
      <div class="con">
        <p>何立峰，男，汉族，1955年2月生，广东兴宁人。</p>
        <p>现任国务院副总理、党组成员。</p>
        <p>1973－1976年　福建省永定县立新知青农场知青</p>
        <p>2018－　十三届全国政协副主席</p>
      </div>
      <div>无关推荐</div>
    </body></html>
    """.encode()
    result = await ChinaOfficialProfileAdapter().extract(html, "http://www.cppcc.gov.cn/profile.html")
    assert result["name"] == "何立峰"
    assert result["current_position"] == "现任国务院副总理、党组成员。"
    assert result["timeline"] == [
        {"period": "1973－1976", "position": "福建省永定县立新知青农场知青"},
        {"period": "2018－", "position": "十三届全国政协副主席"},
    ]
    assert "无关导航" not in result["summary"]


async def test_people_profile_point_in_time_layout() -> None:
    html = """
    <html><head><title>天津政协主席何立峰调任国家发改委</title></head><body>
      <div class="p_content clearfix">
        <p>何立峰，男，汉族，1955年2月生，广东兴宁人。</p>
        <p>1973年8月起先后为福建省永定县知青、水电站工人，</p>
        <p>2014.06 国家发展改革委副主任、党组副书记。</p>
      </div>
    </body></html>
    """.encode()
    result = await ChinaOfficialProfileAdapter().extract(html, "http://finance.people.com.cn/profile.html")
    assert result["name"] == "何立峰"
    assert result["timeline"] == [
        {"period": "1973年8月", "position": "先后为福建省永定县知青、水电站工人，"},
        {"period": "2014.06", "position": "国家发展改革委副主任、党组副书记。"},
    ]
