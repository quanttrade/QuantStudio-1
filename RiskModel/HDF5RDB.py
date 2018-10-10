# coding=utf-8
import os
import datetime as dt
from multiprocessing import Lock

import numpy as np
import pandas as pd
import h5py
from traits.api import Directory

from QuantStudio.Tools.FileFun import listDirFile
from QuantStudio.Tools.DateTimeFun import cutDateTime
from .RiskDataBase import RiskDataBase, FactorRDB
from QuantStudio import __QS_Object__, __QS_Error__, __QS_LibPath__

class HDF5RDB(RiskDataBase):
    """基于 HDF5 文件的风险数据库"""
    MainDir = Directory(label="主目录", arg_type="Directory", order=0)
    def __init__(self, sys_args={}, config_file=None, **kwargs):
        self._TableDT = {}#{表名：[时点]}
        self._DataLock = Lock()
        self._Suffix = "hdf5"
        self._isAvailable = False
        return super().__init__(sys_args=sys_args, config_file=(__QS_LibPath__+os.sep+"HDF5RDBConfig.json" if config_file is None else config_file), **kwargs)
    def connect(self):
        if not os.path.isdir(self.MainDir): raise __QS_Error__("不存在 HDF5RDB 的主目录: %s!" % self.MainDir)
        AllTables = listDirFile(self.MainDir, suffix=self._Suffix)
        TableDT = {}#{表名：[时点]}
        with self._DataLock:
            for iTable in AllTables:
                with h5py.File(self.MainDir+os.sep+iTable+"."+self._Suffix, mode="r") as iFile:
                    if "Cov" in iFile:
                        iDTs = sorted(iFile["Cov"])
                        TableDT[iTable] = [dt.datetime.strptime(ijDT, "%Y-%m-%d %H:%M:%S.%f") for ijDT in iDTs]
        self._TableDT = TableDT
        self._isAvailable = True
        return 0
    def disconnect(self):
        self._isAvailable = False
        return 0
    def isAvailable(self):
        return self._isAvailable
    @property
    def TableNames(self):
        return sorted(self._TableDT)
    def getTableMetaData(self, table_name, key=None):
        with self._DataLock:
            with h5py.File(self.MainDir+os.sep+table_name+"."+self._Suffix) as File:
                if key is None: return pd.Series(File.attrs)
                elif key in File.attrs: return File.attrs[key]
                else: return None
    def setTableMetaData(self, table_name, key=None, value=None, meta_data=None):
        with self._DataLock:
            with h5py.File(self.MainDir+os.sep+table_name+"."+self._Suffix) as File:
                if meta_data is None: meta_data = {}
                if key is not None: meta_data[key] = value
                for iKey, iValue in meta_data.items():
                    if iKey in File.attrs:
                        del File.attrs[iKey]
                    if (isinstance(iValue, np.ndarray)) and (iValue.dtype==np.dtype("O")):
                        File.attrs.create(iKey, data=iValue, dtype=h5py.special_dtype(vlen=str))
                    elif iValue is not None:
                        File.attrs[iKey] = iValue
        return 0
    def renameTable(self, old_table_name, new_table_name):
        if old_table_name not in self._TableDT: raise __QS_Error__("表: '%s' 不存在!" % old_table_name)
        if (new_table_name!=old_table_name) and (new_table_name in self._TableDT): raise __QS_Error__("表: '%s' 已存在!" % new_table_name)
        with self._DataLock:
            os.rename(self.MainDir+os.sep+old_table_name+"."+self._Suffix, self.MainDir+os.sep+new_table_name+"."+self._Suffix)
        self._TableDT[new_table_name] = self._TableDT.pop(old_table_name)
        return 0
    def deleteTable(self, table_name):
        with self._DataLock:
            iFilePath = self.MainDir+os.sep+table_name+"."+self._Suffix
            if os.path.isfile(iFilePath): os.remove(iFilePath)
        self._TableDT.pop(table_name, None)
        return 0
    def getTableDateTime(self, table_name, start_dt=None, end_dt=None):
        return cutDateTime(self._TableDT[table_name], start_dt, end_dt)
    def deleteDateTime(self, table_name, dts):
        with self._DataLock:
            with h5py.File(self.MainDir+os.sep+table_name+"."+self._Suffix) as File:
                CovGroup = File["Cov"]
                for iDT in dts:
                    if iDT not in self._TableDT[table_name]: continue
                    iDTStr = iDT.strftime("%Y-%m-%d %H:%M:%S.%f")
                    if iDTStr in CovGroup: del CovGroup[iDTStr]
        self._TableDT[table_name] = sorted(set(self._TableDT[table_name]).difference(dts))
        if not self._TableDT[table_name]: self.deleteTable(table_name)
        return 0
    def readCov(self, table_name, dts, ids=None):
        Data = {}
        with self._DataLock:
            with h5py.File(self.MainDir+os.sep+table_name+"."+self._Suffix, mode="r") as File:
                CovGroup = File["Cov"]
                for iDT in dts:
                    iDTStr = iDT.strftime("%Y-%m-%d %H:%M:%S.%f")
                    if iDTStr not in CovGroup: continue
                    iGroup = CovGroup[iDTStr]
                    iIDs = iGroup["ID"][...]
                    iCov = pd.DataFrame(iGroup["Data"][...], index=iIDs, columns=iIDs)
                    if ids is not None:
                        if iCov.index.intersection(ids).shape[0]>0: iCov = iCov.loc[ids]
                        else: iCov = pd.DataFrame(index=ids, columns=ids)
                    Data[iDT] = iCov
        if Data: return pd.Panel(Data).loc[dts]
        if ids: return pd.Panel(items=dts, major_axis=ids, minor_axis=ids)
        return pd.Panel(items=dts)
    def writeData(self, table_name, idt, icov):
        TablePath = self.MainDir+os.sep+table_name+"."
        with self._DataLock:
            with h5py.File(self.MainDir+os.sep+table_name+"."+self._Suffix) as File:
                iDTStr = idt.strftime("%Y-%m-%d %H:%M:%S.%f")
                if "Cov" not in File: CovGroup = File.create_group("Cov")
                else: CovGroup = File["Cov"]
                if iDTStr in CovGroup: del CovGroup[iDTStr]
                iGroup = CovGroup.create_group(iDTStr)
                iGroup.create_dataset("ID", shape=(icov.shape[0], ), dtype=h5py.special_dtype(vlen=str), data=icov.index.values)
                iGroup.create_dataset("Data", shape=icov.shape, dtype=np.float, data=icov.values)
        if idt not in self._TableDT[table_name]:
            self._TableDT[table_name].append(idt)
            self._TableDT[table_name].sort()
        return 0

class HDF5FRDB(FactorRDB):
    """基于 HDF5 文件的多因子风险数据库"""
    MainDir = Directory(label="主目录", arg_type="Directory", order=0)
    def __init__(self, sys_args={}, config_file=None, **kwargs):
        self._TableDT = {}#{表名：[时点]}
        self._DataLock = Lock()
        self._Suffix = "h5"
        self._isAvailable = False
        return super().__init__(sys_args=sys_args, config_file=(__QS_LibPath__+os.sep+"HDF5FRDBConfig.json" if config_file is None else config_file), **kwargs)
    def connect(self):
        if not os.path.isdir(self.MainDir): raise __QS_Error__("不存在 HDF5FRDB 的主目录: %s!" % self.MainDir)
        AllTables = listDirFile(self.MainDir, suffix=self._Suffix)
        TableDT = {}#{表名：[时点]}
        with self._DataLock:
            for iTable in AllTables:
                with h5py.File(self.MainDir+os.sep+iTable+"."+self._Suffix, mode="r") as iFile:
                    if "SpecificRisk" in iFile:
                        iDTs = sorted(iFile["SpecificRisk"])
                        TableDT[iTable] = [dt.datetime.strptime(ijDT, "%Y-%m-%d %H:%M:%S.%f") for ijDT in iDTs]
        self._TableDT = TableDT
        self._isAvailable = True
        return 0
    def disconnect(self):
        self._isAvailable = False
        return 0
    def isAvailable(self):
        return self._isAvailable
    @property
    def TableNames(self):
        return sorted(self._TableDT)    
    def getTableMetaData(self, table_name, key=None):
        return HDF5RDB.getTableMetaData(self, table_name, key=key)
    def setTableMetaData(self, table_name, key=None, value=None, meta_data=None):
        return HDF5RDB.setTableMetaData(self, table_name, key=key, value=value, meta_data=meta_data)
    def renameTable(self, old_table_name, new_table_name):
        return HDF5RDB.renameTable(self, old_table_name, new_table_name)
    def deleteTable(self, table_name):
        return HDF5RDB.deleteTable(self, table_name)
    def getTableFactor(self, table_name):
        with self._DataLock:
            with h5py.File(self.MainDir+os.sep+table_name+"."+self._Suffix, mode="r") as File:
                DTStr = self._TableDT[table_name][-1].strftime("%Y-%m-%d %H:%M:%S.%f")
                Group = File["FactorCov"]
                if DTStr in Group: return sorted(Group[DTStr]["Factor"][...])
                else: return []
    def getTableDateTime(self, table_name, start_dt=None, end_dt=None):
        return cutDateTime(self._TableDT[table_name], start_dt, end_dt)
    def getTableID(self, table_name, idt=None):
        if idt is None: idt = self._TableDT[table_name][-1]
        with self._DataLock:
            with h5py.File(self.MainDir+os.sep+table_name+"."+self._Suffix, mode="r") as File:
                DTStr = self._TableDT[table_name][-1].strftime("%Y-%m-%d %H:%M:%S.%f")
                Group = File["SpecificRisk"]
                if DTStr in Group: return sorted(Group[DTStr]["ID"][...])
                else: return []
    def getFactorReturnDateTime(self, table_name, start_dt=None, end_dt=None):
        with self._DataLock:
            with h5py.File(self.MainDir+os.sep+table_name+"."+self._Suffix, mode="r") as File:
                DTs = sorted(File["FactorReturn"])
        return cutDateTime(DTs, start_dt=start_dt, end_dt=end_dt)
    def getSpecificReturnDateTime(self, table_name, start_dt=None, end_dt=None):
        with self._DataLock:
            with h5py.File(self.MainDir+os.sep+table_name+"."+self._Suffix, mode="r") as File:
                DTs = sorted(File["SpecificReturn"])
        return cutDateTime(DTs, start_dt=start_dt, end_dt=end_dt)
    def readCov(self, table_name, dts, ids=None):
        FactorCov = self.readFactorCov(table_name, dts=dts)
        FactorData = self.readFactorData(table_name, dts=dts, ids=ids)
        SpecificRisk = self.readSpecificRisk(table_name, dts=dts, ids=ids)
        Data = {}
        if ids is None:
            ids = SpecificRisk.index
            FactorData = FactorData.loc[:, :, ids]
        for iDT in FactorCov.items:
            iFactorData = FactorData.loc[:, iDT].values
            iCov = np.dot(np.dot(iFactorData, FactorCov.loc[iDT].values), iFactorData) + np.diag(SpecificRisk.loc[iDT].values**2)
            Data[iDT] = pd.DataFrame(iCov, index=ids, columns=ids)
        return pd.Panel(Data).loc[dts]
    def readFactorCov(self, table_name, dts):
        Data = {}
        with self._DataLock:
            with h5py.File(self.MainDir+os.sep+table_name+"."+self._Suffix, mode="r") as File:
                Group = File["FactorCov"]
                for iDT in dts:
                    iDTStr = iDT.strftime("%Y-%m-%d %H:%M:%S.%f")
                    if iDTStr not in Group: continue
                    iGroup = Group[iDTStr]
                    iFactors = iGroup["Factor"][...]
                    Data[iDT] = pd.DataFrame(iGroup["Data"][...], index=iFactors, columns=iFactors)
        if Data: return pd.Panel(Data).loc[dts]
        return pd.Panel(items=dts)
    def readSpecificRisk(self, table_name, dts, ids=None):
        Data = {}
        with self._DataLock:
            with h5py.File(self.MainDir+os.sep+table_name+"."+self._Suffix, mode="r") as File:
                Group = File["SpecificRisk"]
                for iDT in dts:
                    iDTStr = iDT.strftime("%Y-%m-%d %H:%M:%S.%f")
                    if iDTStr not in Group: continue
                    iGroup = Group[iDTStr]
                    Data[iDT] = pd.Series(iGroup["Data"][...], index=iGroup["ID"][...])
        if not Data: return pd.DataFrame(index=dts, columns=([] if ids is None else ids))
        Data = pd.DataFrame(Data).T.loc[dts]
        if ids is not None:
            if Data.columns.intersection(ids).shape[0]>0: Data = Data.loc[ids]
            else: Data = pd.DataFrame(index=dts, columns=ids)
        return Data
    def readFactorData(self, table_name, dts, ids=None):
        Data = {}
        with self._DataLock:
            with h5py.File(self.MainDir+os.sep+table_name+"."+self._Suffix, mode="r") as File:
                Group = File["FactorData"]
                for iDT in dts:
                    iDTStr = iDT.strftime("%Y-%m-%d %H:%M:%S.%f")
                    if iDTStr not in Group: continue
                    iGroup = Group[iDTStr]
                    Data[iDT] = pd.DataFrame(iGroup["Data"][...], index=iGroup["ID"][...], columns=iGroup["Factor"][...]).T
        if not Data: return pd.Panel(items=[], index=dts, columns=([] if ids is None else ids))
        Data = pd.Panel(Data).swapaxes(0, 1).loc[:, dts, :]
        if ids is not None:
            if Data.minor_axis.intersection(ids).shape[0]>0: Data = Data.loc[:, :, ids]
            else: Data = pd.Panel(items=Data.items, major_axis=dts, minor_axis=ids)
        return Data
    def readFactorReturn(self, table_name, dts):
        Data = {}
        with self._DataLock:
            with h5py.File(self.MainDir+os.sep+table_name+"."+self._Suffix, mode="r") as File:
                Group = File["FactorReturn"]
                for iDT in dts:
                    iDTStr = iDT.strftime("%Y-%m-%d %H:%M:%S.%f")
                    if iDTStr not in Group: continue
                    iGroup = Group[iDTStr]
                    Data[iDT] = pd.Series(iGroup["Data"][...], index=iGroup["Factor"][...])
        if not Data: return pd.DataFrame(index=dts, columns=[])
        return pd.DataFrame(Data).T.loc[dts]
    def readSpecificReturn(self, table_name, dts, ids=None):
        Data = {}
        with self._DataLock:
            with h5py.File(self.MainDir+os.sep+table_name+"."+self._Suffix, mode="r") as File:
                Group = File["SpecificReturn"]
                for iDT in dts:
                    iDTStr = iDT.strftime("%Y-%m-%d %H:%M:%S.%f")
                    if iDTStr not in Group: continue
                    iGroup = Group[iDTStr]
                    Data[iDT] = pd.Series(iGroup["Data"][...], index=iGroup["ID"][...])
        if not Data: return pd.DataFrame(index=dts, columns=([] if ids is None else ids))
        Data = pd.DataFrame(Data).T.loc[dts]
        if ids is not None:
            if Data.columns.intersection(ids).shape[0]>0: Data = Data.loc[ids]
            else: Data = pd.DataFrame(index=dts, columns=ids)
        return Data
    def writeData(self, table_name, idt, factor_data=None, factor_cov=None, specific_risk=None, factor_ret=None, specific_ret=None, **kwargs):
        iDTStr = idt.strftime("%Y-%m-%d %H:%M:%S.%f")
        StrType = h5py.special_dtype(vlen=str)
        with self._DataLock:
            with h5py.File(self.MainDir+os.sep+table_name+"."+self._Suffix) as File:
                if factor_data is not None:
                    if "FactorData" not in File: Group = File.create_group("FactorData")
                    else: Group = File["FactorData"]
                    if iDTStr in Group: del Group[iDTStr]
                    iGroup = Group.create_group(iDTStr)
                    iGroup.create_dataset(name="Factor", shape=(factor_data.shape[1], ), dtype=StrType, data=factor_data.columns.values)
                    iGroup.create_dataset(name="ID", shape=(factor_data.shape[0], ), dtype=StrType, data=factor_data.index.values)
                    iGroup.create_dataset(name="Data", shape=factor_data.shape, dtype=np.float, data=factor_data.values)
                if factor_cov is not None:
                    if "FactorCov" not in File: Group = File.create_group("FactorCov")
                    else: Group = File["FactorCov"]
                    if iDTStr in Group: del Group[iDTStr]
                    iGroup = Group.create_group(iDTStr)
                    iGroup.create_dataset(name="Factor", shape=(factor_cov.shape[0], ), dtype=StrType, data=factor_cov.index.values)
                    iGroup.create_dataset(name="Data", shape=factor_cov.shape, dtype=np.float, data=factor_cov.values)
                if specific_risk is not None:
                    if "SpecificRisk" not in File: Group = File.create_group("SpecificRisk")
                    else: Group = File["SpecificRisk"]
                    if iDTStr in Group: del Group[iDTStr]
                    iGroup = Group.create_group(iDTStr)
                    iGroup.create_dataset(name="ID", shape=(specific_risk.shape[0], ), dtype=StrType, data=specific_risk.index.values)
                    iGroup.create_dataset(name="Data", shape=specific_risk.shape, dtype=np.float, data=specific_risk.values)
                if factor_ret is not None:
                    if "FactorReturn" not in File: Group = File.create_group("FactorReturn")
                    else: Group = File["FactorReturn"]
                    if iDTStr in Group: del Group[iDTStr]
                    iGroup = Group.create_group(iDTStr)
                    iGroup.create_dataset(name="Factor", shape=(factor_ret.shape[0], ), dtype=StrType, data=factor_ret.index.values)
                    iGroup.create_dataset(name="Data", shape=factor_ret.shape, dtype=np.float, data=factor_ret.values)
                if specific_ret is not None:
                    if "SpecificReturn" not in File: Group = File.create_group("SpecificReturn")
                    else: Group = File["SpecificReturn"]
                    if iDTStr in Group: del Group[iDTStr]
                    iGroup = Group.create_group(iDTStr)
                    iGroup.create_dataset(name="ID", shape=(specific_ret.shape[0], ), dtype=StrType, data=specific_ret.index.values)
                    iGroup.create_dataset(name="Data", shape=specific_ret.shape, dtype=np.float, data=specific_ret.values)
                for iKey, iValue in kwargs.items():
                    if iKey not in File: Group = File.create_group(iKey)
                    else: Group = File[iKey]
                    if iDTStr in Group: del Group[iDTStr]
                    iGroup = Group.create_group(iDTStr)
                    iGroup.create_dataset(name="index", shape=(iValue.shape[0], ), dtype=StrType, data=iValue.index.values)
                    iGroup.create_dataset(name="Data", shape=iValue.shape, dtype=np.float, data=iValue.values)
                    if isinstance(iValue, pd.DataFrame): iGroup.create_dataset(name="columns", shape=(iValue.shape[1], ), dtype=StrType, data=iValue.columns.values)
        return 0