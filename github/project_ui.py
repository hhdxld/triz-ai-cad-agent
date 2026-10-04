"""私人项目库与可移植设计导出；打开已有成果不再次调用 API 或收费。"""
import json
import streamlit as st
from business import BusinessError


def render_project_exports(result: dict, format_report) -> None:
    """参数文件可再次上传；报告不包含服务器路径、密码或模型密钥。"""
    parameters=json.dumps(result['input_parameters'],ensure_ascii=False,indent=2,allow_nan=False)
    st.download_button('下载参数 JSON',parameters,'cad-parameters.json','application/json',key='design_parameters')
    report='# CAD 设计报告\n\n'+format_report(result)
    report+='\n\n## 参数（长度单位 mm）\n\n```json\n'+parameters+'\n```\n'
    report+='\n本报告来自参数化几何计算；承载、疲劳与制造公差仍需工程核验。\n'
    st.download_button('下载设计报告',report,'cad-design-report.md','text/markdown',key='design_report')


def render_projects(store, user: dict | None, latest: dict | None, format_report) -> None:
    """保存本人订单引用，支持跨登录恢复、重命名与确认删除。"""
    st.subheader('我的项目')
    st.caption('保存、打开和下载已有成果免费；修改后重新生成按当前演示报价计一次。最多保存 50 个项目。')
    if not user:
        st.info('请登录后保存项目。')
        return
    notice=st.session_state.pop('project_notice','')
    if notice:
        st.success(notice)
    if latest and latest.get('service_order_id'):
        with st.form('project_save'):
            name=st.text_input('当前设计的项目名称',value='我的设计',max_chars=80,key='project_name')
            if st.form_submit_button('保存当前设计'):
                try:
                    store.save_project(user['id'],latest['service_order_id'],name)
                    st.session_state.project_notice='项目已保存；同一成果重复保存只更新名称。'
                    st.rerun()
                except BusinessError as exc:
                    st.error(str(exc))
    records=store.projects(user['id'])
    if not records:
        st.info('还没有保存的项目。生成模型后，可在这里命名保存。')
        return
    lookup={r['id']:r for r in records}
    if st.session_state.get('project_selected') not in lookup:
        st.session_state.pop('project_selected',None)
    selected=st.selectbox('选择已保存项目',list(lookup),format_func=lambda key:lookup[key]['name']+' · '+lookup[key]['updated_at'][:10],key='project_selected')
    st.caption('更新于（UTC）：'+lookup[selected]['updated_at'])
    if st.button('打开项目',key='project_open',type='primary'):
        try:
            result=store.load_project(user['id'],selected)
            st.session_state.latest_result=result
            st.session_state.last_params=result['input_parameters']
            st.session_state.editor_sync=True
            st.session_state.last_error=''
            st.session_state.messages=[{'role':'assistant','content':'已打开保存的项目，未重新生成或扣费。\n\n'+format_report(result)}]
            st.session_state.project_notice='已恢复模型和参数，可在三维预览或尺寸编辑中继续操作。'
            st.rerun()
        except BusinessError as exc:
            st.error(str(exc))
    with st.form('project_rename'):
        renamed=st.text_input('新的项目名称',max_chars=80,key='project_rename_value')
        if st.form_submit_button('重命名项目'):
            try:
                store.save_project(user['id'],lookup[selected]['order_id'],renamed)
                st.session_state.project_notice='项目已重命名。'
                st.rerun()
            except BusinessError as exc:
                st.error(str(exc))
    with st.expander('删除项目记录'):
        confirmed=st.checkbox('确认删除所选项目记录（保留历史订单和模型文件）',key='project_delete_confirm')
        if st.button('删除项目',key='project_delete',disabled=not confirmed):
            try:
                store.delete_project(user['id'],selected)
                st.session_state.pop('project_selected',None)
                st.session_state.pop('project_delete_confirm',None)
                st.session_state.project_notice='项目记录已删除。'
                st.rerun()
            except BusinessError as exc:
                st.error(str(exc))
